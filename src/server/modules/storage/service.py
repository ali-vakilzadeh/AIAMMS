"""Storage Module - Object storage abstraction with local, MinIO, and S3 adapters."""

import io
import os
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, BinaryIO, AsyncIterator
from uuid import UUID

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow


logger = get_logger("storage")


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def put(self, key: str, stream: BinaryIO, mime: str, max_bytes: int) -> int:
        """Upload a file. Returns bytes written."""
        pass
    
    @abstractmethod
    async def get(self, key: str) -> AsyncIterator[bytes]:
        """Stream download a file."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a file (idempotent)."""
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if file exists."""
        pass
    
    @abstractmethod
    async def presigned_url(self, key: str, ttl_s: int, method: str) -> str:
        """Generate presigned URL for access."""
        pass
    
    @abstractmethod
    async def health_check(self) -> HealthReport:
        """Check backend health."""
        pass


class LocalBackend(StorageBackend):
    """Local filesystem storage backend."""
    
    def __init__(self, root_path: str):
        self.root = Path(root_path)
        self.root.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage backend initialized at {self.root}")
    
    def _path(self, key: str) -> Path:
        """Get full path for a key, rejecting directory traversal."""
        if ".." in key or key.startswith("/"):
            raise ValueError(f"Invalid key: {key}")
        return self.root / key
    
    async def put(self, key: str, stream: BinaryIO, mime: str, max_bytes: int) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        total = 0
        with open(path, "wb") as f:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                if total + len(chunk) > max_bytes:
                    raise ValueError(f"SIZE_EXCEEDED: {total + len(chunk)} > {max_bytes}")
                f.write(chunk)
                total += len(chunk)
        
        logger.debug(f"Stored {key} ({total} bytes) at {path}")
        return total
    
    async def get(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk
    
    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()
            logger.debug(f"Deleted {key}")
    
    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return path.exists()
    
    async def presigned_url(self, key: str, ttl_s: int, method: str) -> str:
        # For local backend, return file:// URL
        path = self._path(key)
        return f"file://{path.absolute()}"
    
    async def health_check(self) -> HealthReport:
        ts = utcnow()
        try:
            # Write-read-delete probe
            probe_key = ".health/probe.txt"
            probe_path = self._path(probe_key)
            probe_path.parent.mkdir(parents=True, exist_ok=True)
            
            test_data = b"health probe"
            with open(probe_path, "wb") as f:
                f.write(test_data)
            
            with open(probe_path, "rb") as f:
                read_data = f.read()
            
            probe_path.unlink()
            
            if read_data != test_data:
                return HealthReport(
                    module="storage",
                    status=HealthStatus.DEGRADED,
                    checks=[{"name": "probe", "status": "DEGRADED", "detail": "Read mismatch"}],
                    ts=ts,
                )
            
            return HealthReport(
                module="storage",
                status=HealthStatus.OK,
                checks=[{"name": "probe", "status": "OK", "detail": "Write/read/delete OK"}],
                ts=ts,
            )
        except Exception as e:
            return HealthReport(
                module="storage",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "probe", "status": "UNAVAILABLE", "detail": str(e)}],
                ts=ts,
            )


class S3Backend(StorageBackend):
    """S3/MinIO storage backend."""
    
    def __init__(self, endpoint_url: str, bucket: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        self.endpoint_url = endpoint_url
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        
        try:
            import boto3
            from botocore.config import Config
            
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(signature_version="s3v4"),
            )
            logger.info(f"S3 backend initialized: {endpoint_url}/{bucket}")
        except ImportError:
            raise RuntimeError("boto3 not installed. Install with: pip install boto3")
    
    async def put(self, key: str, stream: BinaryIO, mime: str, max_bytes: int) -> int:
        data = stream.read()
        if len(data) > max_bytes:
            raise ValueError(f"SIZE_EXCEEDED: {len(data)} > {max_bytes}")
        
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime,
        )
        return len(data)
    
    async def get(self, key: str) -> AsyncIterator[bytes]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        yield response["Body"].read()
    
    async def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            pass  # Idempotent
    
    async def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
    
    async def presigned_url(self, key: str, ttl_s: int, method: str) -> str:
        # Cap TTL at 1 hour
        ttl_s = min(ttl_s, 3600)
        return self.client.generate_presigned_url(
            "get_object" if method == "GET" else "put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_s,
        )
    
    async def health_check(self) -> HealthReport:
        ts = utcnow()
        try:
            # Probe write-read-delete
            probe_key = ".health/probe.bin"
            test_data = b"health probe"
            
            self.client.put_object(Bucket=self.bucket, Key=probe_key, Body=test_data)
            response = self.client.get_object(Bucket=self.bucket, Key=probe_key)
            read_data = response["Body"].read()
            self.client.delete_object(Bucket=self.bucket, Key=probe_key)
            
            if read_data != test_data:
                return HealthReport(
                    module="storage",
                    status=HealthStatus.DEGRADED,
                    checks=[{"name": "probe", "status": "DEGRADED", "detail": "Read mismatch"}],
                    ts=ts,
                )
            
            return HealthReport(
                module="storage",
                status=HealthStatus.OK,
                checks=[{"name": "probe", "status": "OK", "detail": "S3 probe OK"}],
                ts=ts,
            )
        except Exception as e:
            return HealthReport(
                module="storage",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "probe", "status": "UNAVAILABLE", "detail": str(e)}],
                ts=ts,
            )


# Global backend instance
_backend: Optional[StorageBackend] = None


def backend() -> StorageBackend:
    """Get storage backend by configuration.
    
    Selects adapter based on CMMS_STORAGE__BACKEND (local|minio|s3).
    
    Returns:
        Configured StorageBackend instance
    """
    global _backend
    
    if _backend is not None:
        return _backend
    
    settings = module_settings("storage")
    if settings is None:
        raise RuntimeError("Storage settings not loaded")
    
    backend_type = getattr(settings, "backend", "local")
    
    if backend_type == "local":
        root_path = getattr(settings, "local_root", "/tmp/cmms-storage")
        _backend = LocalBackend(root_path)
        
    elif backend_type in ("s3", "minio"):
        endpoint = getattr(settings, "endpoint_url", "http://localhost:9000")
        bucket = getattr(settings, "bucket", "cmms")
        access_key = getattr(settings, "access_key", "")
        secret_key = getattr(settings, "secret_key", "")
        region = getattr(settings, "region", "us-east-1")
        
        _backend = S3Backend(endpoint, bucket, access_key, secret_key, region)
        
    else:
        raise ValueError(f"Unknown storage backend: {backend_type}")
    
    return _backend


def tenant_key(org_id: UUID, category: str, *parts: str) -> str:
    """Build tenant-scoped storage key.
    
    Format: /org-{org_id}/{category}/{parts...}
    Rejects '..' and absolute segments.
    
    Args:
        org_id: Organization ID for tenant isolation
        category: Category like 'attachments', 'manuals', 'exports'
        *parts: Additional path components
        
    Returns:
        Normalized storage key
        
    Raises:
        ValueError: If any part contains '..' or is absolute
    """
    all_parts = [f"org-{org_id}", category] + list(parts)
    
    for part in all_parts:
        if ".." in part or part.startswith("/"):
            raise ValueError(f"Invalid path segment: {part}")
    
    return "/".join(all_parts)


async def put(key: str, stream: BinaryIO, mime: str, max_bytes: int = 10 * 1024 * 1024) -> int:
    """Upload file to storage.
    
    Args:
        key: Storage key (use tenant_key() for tenant-scoped keys)
        stream: Binary stream to read from
        mime: MIME type of content
        max_bytes: Maximum allowed size (default 10MB)
        
    Returns:
        Bytes written
        
    Raises:
        ValueError: If SIZE_EXCEEDED
    """
    return await backend().put(key, stream, mime, max_bytes)


async def get(key: str) -> AsyncIterator[bytes]:
    """Download file from storage.
    
    Args:
        key: Storage key
        
    Yields:
        File chunks
    """
    async for chunk in backend().get(key):
        yield chunk


async def delete(key: str) -> None:
    """Delete file from storage (idempotent).
    
    Args:
        key: Storage key
    """
    await backend().delete(key)


async def exists(key: str) -> bool:
    """Check if file exists in storage.
    
    Args:
        key: Storage key
        
    Returns:
        True if exists
    """
    return await backend().exists(key)


async def presigned_url(key: str, ttl_s: int = 900, method: str = "GET") -> str:
    """Generate presigned URL for temporary access.
    
    Args:
        key: Storage key
        ttl_s: URL validity in seconds (max 3600)
        method: HTTP method (GET or PUT)
        
    Returns:
        Presigned URL string
    """
    return await backend().presigned_url(key, ttl_s, method)


def sniff_mime(head: bytes) -> str:
    """Sniff MIME type from file header using python-magic.
    
    Args:
        head: First bytes of file (512 bytes recommended)
        
    Returns:
        MIME type string
    """
    try:
        import magic
        mime = magic.from_buffer(head, mime=True)
        return mime or "application/octet-stream"
    except ImportError:
        logger.warning("python-magic not installed, using default MIME")
        return "application/octet-stream"


async def health_check() -> HealthReport:
    """Run storage backend health check.
    
    Returns:
        HealthReport with probe results
    """
    return await backend().health_check()


class StorageService:
    """Published port for storage operations."""
    
    @staticmethod
    def get_backend() -> StorageBackend:
        return backend()
    
    @staticmethod
    def build_tenant_key(org_id: UUID, category: str, *parts: str) -> str:
        return tenant_key(org_id, category, *parts)
    
    @staticmethod
    async def upload(key: str, stream: BinaryIO, mime: str, max_bytes: int = 10*1024*1024) -> int:
        return await put(key, stream, mime, max_bytes)
    
    @staticmethod
    async def download(key: str) -> AsyncIterator[bytes]:
        async for chunk in get(key):
            yield chunk
    
    @staticmethod
    async def remove(key: str) -> None:
        await delete(key)
    
    @staticmethod
    async def check_exists(key: str) -> bool:
        return await exists(key)
    
    @staticmethod
    async def get_presigned_url(key: str, ttl_s: int = 900, method: str = "GET") -> str:
        return await presigned_url(key, ttl_s, method)
    
    @staticmethod
    def detect_mime(head: bytes) -> str:
        return sniff_mime(head)
    
    @staticmethod
    async def check_health() -> HealthReport:
        return await health_check()


class StorageModule(ModuleBase):
    """Storage module implementing ModuleBase protocol."""
    
    name = "storage"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("api", "worker", "beat", "mcp", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Validate storage configuration."""
        logger.info("Configuring Storage module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize storage backend."""
        logger.info("Initializing Storage module")
        backend()  # Initialize backend
        
        # Register service port
        from core.registry import register_service
        register_service("storage", StorageService(), StorageService)
        
    async def start(self) -> None:
        """Start Storage module."""
        logger.info("Storage module started")
        
    async def stop(self) -> None:
        """Stop Storage module."""
        logger.info("Stopping Storage module")
        global _backend
        _backend = None
        
    async def health(self) -> HealthReport:
        """Report storage health."""
        return await health_check()
