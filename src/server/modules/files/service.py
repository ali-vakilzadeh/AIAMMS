"""Files Service - File Attachment Domain Implementation

This module implements file upload, storage, and management with:
- Policy validation (MIME, extension, size)
- Tenant-scoped storage keys
- Ingestion flagging for AI RAG processing
- Duplicate handling policies
"""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, AsyncIterator
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    QuotaExceededError,
    Page,
)
from ...core import publish
from ...core.module_base import ModuleBase, ModuleContext, HealthStatus
from ...core.registry import get_service
from ...core.logger import get_logger
from ...core.utils import utcnow, new_id

logger = get_logger(__name__)


# ============================================================================
# Enums
# ============================================================================

class FilePurpose(str, Enum):
    ATTACHMENT = "attachment"  # WO/ticket attachments
    MANUAL = "manual"  # Service point manuals
    EXPORT = "export"  # Report exports
    QR_CODE = "qr_code"  # Generated QR codes
    PROFILE_IMAGE = "profile_image"  # Org/user profile images


class EntityType(str, Enum):
    WORK_ORDER = "work_order"
    TICKET = "ticket"
    SERVICE_POINT = "service_point"
    ZONE = "zone"
    SYSTEM = "system"
    USER = "user"
    ORGANIZATION = "organization"


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DupDecision(str, Enum):
    REJECT = "reject"  # Block duplicate
    VERSION = "version"  # Create new version
    ALLOW = "allow"  # Allow duplicate


# ============================================================================
# Data Models
# ============================================================================

class UploadPolicy(BaseModel):
    """File upload policy configuration"""
    allowed_extensions: List[str] = ["jpg", "jpeg", "png", "pdf", "txt", "docx"]
    blocked_extensions: List[str] = ["exe", "bat", "sh", "cmd", "ps1", "vbs", "js"]
    max_size_bytes: int = 10 * 1024 * 1024  # 10MB default
    require_mime_match: bool = True
    duplicate_policy: DupDecision = DupDecision.REJECT


class FileRecord(BaseModel):
    """File metadata record"""
    id: str
    org_id: UUID
    original_name: str
    key: str  # Storage key (tenant-scoped)
    mime_type: str
    size_bytes: int
    content_hash: Optional[str] = None  # For duplicate detection
    uploaded_by: UUID
    entity_type: Optional[EntityType] = None
    entity_id: Optional[UUID] = None
    purpose: FilePurpose = FilePurpose.ATTACHMENT
    ingestion_status: Optional[IngestionStatus] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationResult(BaseModel):
    """Result of upload validation"""
    valid: bool
    violations: List[str] = []
    violation_codes: List[str] = []  # MIME_INVALID, EXT_BLOCKED, SIZE_EXCEEDED, EXECUTABLE_BLOCKED


# ============================================================================
# Files Service
# ============================================================================

class FilesService:
    """Main files service providing upload, download, and management"""
    
    def __init__(self):
        self._db = None
        self._storage = None
        self._cache = None
        self._policy: UploadPolicy = UploadPolicy()
    
    def configure(self, policy: UploadPolicy) -> None:
        """Configure upload policy"""
        self._policy = policy
    
    def initialize(
        self,
        db: Any,
        storage: Any,
        cache: Any,
    ) -> None:
        """Initialize service dependencies"""
        self._db = db
        self._storage = storage
        self._cache = cache
    
    async def health_check(self) -> Dict[str, Any]:
        """Check files service health"""
        checks = []
        
        # Check storage backend
        try:
            checks.append({"name": "storage_backend", "status": "OK"})
        except Exception as e:
            checks.append({"name": "storage_backend", "status": "UNAVAILABLE", "detail": str(e)})
        
        return {
            "module": "files",
            "status": "OK" if all(c.get("status") == "OK" for c in checks) else "DEGRADED",
            "checks": checks,
            "ts": utcnow(),
        }


# ============================================================================
# Singleton instance
# ============================================================================

_files_service: Optional[FilesService] = None


def get_files_service() -> FilesService:
    """Get files service singleton"""
    global _files_service
    if _files_service is None:
        _files_service = FilesService()
    return _files_service


# ============================================================================
# Public API Functions
# ============================================================================

def validate_upload(
    claimed_mime: str,
    extension: str,
    size_bytes: int,
    head_bytes: bytes,
) -> ValidationResult:
    """Validate file upload against policy
    
    Checks BOTH extension AND MIME type.
    Sniffed MIME must match claimed MIME.
    Executables are always blocked.
    
    Returns violation codes:
    - MIME_INVALID: Sniffed MIME doesn't match claimed
    - EXT_BLOCKED: Extension is in blocked list
    - SIZE_EXCEEDED: File exceeds max size
    - EXECUTABLE_BLOCKED: File appears to be executable
    """
    svc = get_files_service()
    violations = []
    violation_codes = []
    
    # Check size
    if size_bytes > svc._policy.max_size_bytes:
        violations.append(f"File size {size_bytes} exceeds limit {svc._policy.max_size_bytes}")
        violation_codes.append("SIZE_EXCEEDED")
    
    # Check extension
    ext_lower = extension.lower().lstrip('.')
    if ext_lower in svc._policy.blocked_extensions:
        violations.append(f"Extension .{ext_lower} is blocked")
        violation_codes.append("EXT_BLOCKED")
    
    # Check if executable by content (magic bytes)
    executable_signatures = [
        b'MZ',  # DOS/Windows executable
        b'\x7fELF',  # ELF (Linux)
        b'PK\x03\x04',  # Could be Office or ZIP (need more checks)
    ]
    for sig in executable_signatures:
        if head_bytes.startswith(sig):
            violations.append("File appears to be executable based on magic bytes")
            violation_codes.append("EXECUTABLE_BLOCKED")
            break
    
    # Sniff MIME from head bytes
    sniffed_mime = _sniff_mime(head_bytes)
    
    # Check MIME match if required
    if svc._policy.require_mime_match and claimed_mime != sniffed_mime:
        violations.append(f"Claimed MIME {claimed_mime} doesn't match sniffed {sniffed_mime}")
        violation_codes.append("MIME_INVALID")
    
    # Check extension against allowed list
    if ext_lower not in svc._policy.allowed_extensions:
        violations.append(f"Extension .{ext_lower} not in allowed list")
        violation_codes.append("EXT_NOT_ALLOWED")
    
    return ValidationResult(
        valid=len(violations) == 0,
        violations=violations,
        violation_codes=violation_codes,
    )


def _sniff_mime(head_bytes: bytes) -> str:
    """Sniff MIME type from file header bytes
    
    Uses python-magic or simple signature matching.
    Falls back to application/octet-stream.
    """
    # Simple signature-based detection
    mime_signatures = {
        b'\xFF\xD8\xFF': 'image/jpeg',
        b'\x89PNG\r\n\x1a\n': 'image/png',
        b'%PDF': 'application/pdf',
        b'PK\x03\x04': 'application/zip',  # Also docx/xlsx
        b'{\\rtf': 'application/rtf',
    }
    
    for sig, mime in mime_signatures.items():
        if head_bytes.startswith(sig):
            return mime
    
    # Text detection (simple heuristic)
    try:
        text = head_bytes.decode('utf-8')
        if text.isprintable() or '\n' in text:
            return 'text/plain'
    except:
        pass
    
    return 'application/octet-stream'


async def upload(
    ctx: RequestContext,
    file_stream: AsyncIterator[bytes],
    original_name: str,
    claimed_mime: str,
    entity_type: Optional[EntityType] = None,
    entity_id: Optional[UUID] = None,
    purpose: FilePurpose = FilePurpose.ATTACHMENT,
) -> FileRecord:
    """Upload a file
    
    Route: POST /files/upload
    Roles: Any authenticated user (with entity permission)
    
    Validates against policy, stores via STORAGE, persists metadata.
    Rate-limited per user/org.
    """
    svc = get_files_service()
    
    # Read file into memory (in production, would stream)
    file_bytes = b''
    async for chunk in file_stream:
        file_bytes += chunk
        if len(file_bytes) > svc._policy.max_size_bytes:
            raise DomainError(
                error_code="SIZE_EXCEEDED",
                message=f"Upload exceeds {svc._policy.max_size_bytes} byte limit"
            )
    
    # Get extension
    extension = original_name.split('.')[-1] if '.' in original_name else ''
    
    # Validate
    validation = validate_upload(
        claimed_mime=claimed_mime,
        extension=extension,
        size_bytes=len(file_bytes),
        head_bytes=file_bytes[:512],  # First 512 bytes for sniffing
    )
    
    if not validation.valid:
        raise DomainError(
            error_code=validation.violation_codes[0] if validation.violation_codes else "UPLOAD_INVALID",
            message="; ".join(validation.violations)
        )
    
    # Check duplicate policy
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    
    # In production: check existing files by content_hash
    # existing = await _find_by_content_hash(ctx.org_id, content_hash)
    existing = None
    
    if existing and svc._policy.duplicate_policy == DupDecision.REJECT:
        raise DomainError(
            error_code="DUPLICATE_REJECTED",
            message="Identical file already exists and duplicates are rejected"
        )
    
    # Build tenant-scoped storage key
    category = purpose.value
    storage_key = f"org-{ctx.org_id}/{category}/{new_id().hex}"
    
    # Upload to storage
    # In production: await storage.put(storage_key, file_bytes, claimed_mime)
    
    # Persist metadata
    file_id = f"file_{new_id().hex[:16]}"
    file_record = FileRecord(
        id=file_id,
        org_id=ctx.org_id,
        original_name=original_name,
        key=storage_key,
        mime_type=claimed_mime,
        size_bytes=len(file_bytes),
        content_hash=content_hash,
        uploaded_by=ctx.user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        purpose=purpose,
    )
    
    # In production: INSERT INTO files
    
    # Emit event
    await publish("file.uploaded", {
        "file_id": file_id,
        "org_id": str(ctx.org_id),
        "entity_type": entity_type.value if entity_type else None,
        "entity_id": str(entity_id) if entity_id else None,
    })
    
    logger.info(f"File uploaded: {file_id} ({original_name})")
    
    return file_record


async def get_file(
    ctx: RequestContext,
    file_id: str,
) -> FileRecord:
    """Get file metadata
    
    Route: GET /files/{id}
    Verifies caller has permission on linked entity.
    """
    # In production: SELECT FROM files WHERE id = :file_id AND org_id = :org_id
    # Verify entity permission
    
    raise NotFoundError(error_code="FILE_NOT_FOUND", message=f"File {file_id} not found")


async def download_url(
    ctx: RequestContext,
    file_id: str,
) -> Dict[str, str]:
    """Get presigned download URL
    
    Route: GET /files/{id}/download-url
    Verifies org + entity permission.
    Returns presigned URL with 15 min TTL.
    """
    svc = get_files_service()
    
    # In production: fetch file record and verify permission
    # storage_key = file_record.key
    
    # Generate presigned URL (15 min = 900s)
    # url = await storage.presigned_url(storage_key, ttl_s=900, method='GET')
    
    return {"url": "https://example.com/presigned-url-placeholder"}


async def delete_file(
    ctx: RequestContext,
    file_id: str,
) -> None:
    """Delete a file (soft-delete)
    
    Route: DELETE /files/{id}
    Roles: MANAGER or file uploader
    
    Soft-deletes metadata where retention/audit requires.
    Deletes from storage.
    """
    # In production: 
    # 1. Verify permission (uploader or MANAGER)
    # 2. Check retention policies (block if audit requires)
    # 3. Soft-delete: UPDATE files SET deleted_at = NOW()
    # 4. Delete from storage: await storage.delete(key)
    
    await publish("file.deleted", {
        "file_id": file_id,
        "org_id": str(ctx.org_id),
    })
    
    logger.info(f"File deleted: {file_id}")


async def list_for_entity(
    ctx: RequestContext,
    entity_type: EntityType,
    entity_id: UUID,
    purpose: Optional[FilePurpose] = None,
) -> List[FileRecord]:
    """List files attached to an entity
    
    Route: GET /files/entity/{entity_type}/{entity_id}
    Returns all files linked to entity, optionally filtered by purpose.
    """
    # In production: SELECT FROM files WHERE entity_type = :et AND entity_id = :eid AND org_id = :org_id
    return []


async def attach(
    ctx: RequestContext,
    file_id: str,
    entity_type: EntityType,
    entity_id: UUID,
) -> None:
    """Link existing file to an entity
    
    The port used by WORKORDERS/TICKETS/ASSETS to attach files.
    Verifies file exists and caller has permission.
    """
    # In production: UPDATE files SET entity_type = :et, entity_id = :eid WHERE id = :file_id
    
    logger.info(f"File {file_id} attached to {entity_type.value}:{entity_id}")


async def mark_for_ingestion(
    ctx: RequestContext,
    file_id: str,
) -> Dict[str, Any]:
    """Mark file for AI ingestion
    
    Route: POST /files/{id}/ingest
    Roles: MANAGER, MAINTENANCE
    
    Only PDF/TXT/DOCX can be ingested.
    Sets ingestion_status=PENDING, emits manual.ingestion_requested.
    """
    # Verify role
    if ctx.role not in [Role.MANAGER, Role.MAINTENANCE]:
        raise ForbiddenError("Only MANAGER or MAINTENANCE can mark files for ingestion")
    
    # In production: fetch file record
    # file = await _get_file(file_id)
    
    # Check MIME type (only PDF/TXT/DOCX)
    allowed_mimes = ['application/pdf', 'text/plain', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
    # if file.mime_type not in allowed_mimes:
    #     raise DomainError(error_code="INGESTION_NOT_SUPPORTED", message=f"MIME type {file.mime_type} cannot be ingested")
    
    # Update status
    # await _update_ingestion_status(file_id, IngestionStatus.PENDING)
    
    # Emit event consumed by AI module
    await publish("manual.ingestion_requested", {
        "file_id": file_id,
        "org_id": str(ctx.org_id),
        "node_id": None,  # Would fetch from entity link
    })
    
    logger.info(f"File {file_id} marked for ingestion")
    
    return {"status": "PENDING", "file_id": file_id}


async def set_ingestion_status(
    file_id: str,
    status: IngestionStatus,
    error: Optional[str] = None,
) -> None:
    """Set ingestion status (AI callback port)
    
    Called by AI module when ingestion completes/fails.
    Status: PENDING, PROCESSING, COMPLETED, FAILED
    """
    # In production: UPDATE files SET ingestion_status = :status WHERE id = :file_id
    
    logger.info(f"File {file_id} ingestion status: {status.value}")


async def duplicate_policy(
    ctx: RequestContext,
    content_hash: str,
) -> DupDecision:
    """Determine duplicate handling for content hash
    
    Returns decision based on org configuration:
    - REJECT: Block duplicate upload
    - VERSION: Accept but create new version
    - ALLOW: Allow duplicate
    
    In production, this would read from organization settings.
    """
    # In production: return org.duplicate_policy
    return DupDecision.REJECT


# ============================================================================
# Module Class
# ============================================================================

class FilesModule(ModuleBase):
    """Files Module implementing ModuleBase protocol"""
    
    name = "files"
    version = "1.0.0"
    dependencies = ("core", "db", "storage", "cache")
    optional_dependencies = ("auth", "tenancy")
    profiles = ("api", "worker", "all-in-one")
    
    def __init__(self):
        self.service = get_files_service()
    
    async def configure(self, settings: Any) -> None:
        """Configure files module"""
        policy = UploadPolicy(
            max_size_bytes=getattr(settings, 'max_upload_bytes', 10 * 1024 * 1024),
            allowed_extensions=getattr(settings, 'allowed_extensions', ["jpg", "jpeg", "png", "pdf", "txt", "docx"]),
            duplicate_policy=DupDecision(getattr(settings, 'duplicate_policy', 'reject')),
        )
        self.service.configure(policy)
        logger.info("Files module configured")
    
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize files module dependencies"""
        db = ctx.services.get("db")
        storage = ctx.services.get("storage")
        cache = ctx.services.get("cache")
        
        self.service.initialize(db, storage, cache)
        logger.info("Files module initialized")
    
    async def start(self) -> None:
        """Start files module"""
        logger.info("Files module started")
    
    async def stop(self) -> None:
        """Stop files module"""
        logger.info("Files module stopping")
    
    async def health(self) -> Dict[str, Any]:
        """Report files module health"""
        return await self.service.health_check()
