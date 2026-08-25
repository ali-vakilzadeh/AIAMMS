"""Files Module - File Attachment Domain

This module implements file upload, storage, and management with:
- Policy validation (MIME, extension, size)
- Tenant-scoped storage keys
- Ingestion flagging for AI RAG processing
- Duplicate handling policies
"""

from .service import (
    FilesService,
    validate_upload,
    upload,
    get_file,
    download_url,
    delete_file,
    list_for_entity,
    attach,
    mark_for_ingestion,
    set_ingestion_status,
    duplicate_policy,
    # Data models
    FileRecord,
    UploadPolicy,
    DupDecision,
    IngestionStatus,
    # Enums
    FilePurpose,
    EntityType,
)

__all__ = [
    "FilesService",
    "validate_upload",
    "upload",
    "get_file",
    "download_url",
    "delete_file",
    "list_for_entity",
    "attach",
    "mark_for_ingestion",
    "set_ingestion_status",
    "duplicate_policy",
    "FileRecord",
    "UploadPolicy",
    "DupDecision",
    "IngestionStatus",
    "FilePurpose",
    "EntityType",
]
