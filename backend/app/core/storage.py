"""Storage abstraction layer supporting Local and extensible to S3/Cloud Storage."""

from abc import ABC, abstractmethod
import hashlib
from pathlib import Path
from typing import Optional
import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BaseStorageService(ABC):
    """Abstract interface for document file storage."""

    @abstractmethod
    def save_file(
        self,
        tenant_id: uuid.UUID,
        file_id: uuid.UUID,
        content: bytes,
        extension: str = "pdf",
    ) -> str:
        """Persist file content and return storage path."""
        pass

    @abstractmethod
    def get_file(self, storage_path: str) -> bytes:
        """Retrieve file content by storage path."""
        pass

    @abstractmethod
    def delete_file(self, storage_path: str) -> bool:
        """Remove file by storage path if it exists."""
        pass

    @staticmethod
    def compute_checksum(content: bytes) -> str:
        """Compute SHA-256 checksum of raw file bytes."""
        return hashlib.sha256(content).hexdigest()


class LocalStorageService(BaseStorageService):
    """Local filesystem storage implementation with tenant isolation."""

    def __init__(self, base_dir: Optional[str] = None):
        root = base_dir or settings.STORAGE_LOCAL_DIR
        self.base_path = Path(root).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_tenant_dir(self, tenant_id: uuid.UUID) -> Path:
        """Resolve and create isolated directory for tenant."""
        tenant_dir = (self.base_path / "documents" / str(tenant_id)).resolve()
        # Prevent directory traversal attacks
        if not str(tenant_dir).startswith(str(self.base_path)):
            raise ValueError("Invalid storage path attempt.")
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir

    def save_file(
        self,
        tenant_id: uuid.UUID,
        file_id: uuid.UUID,
        content: bytes,
        extension: str = "pdf",
    ) -> str:
        """Store bytes under {base_dir}/documents/{tenant_id}/{file_id}.{extension}."""
        tenant_dir = self._get_tenant_dir(tenant_id)
        clean_ext = extension.lstrip(".")
        filename = f"{file_id}.{clean_ext}"
        target_path = (tenant_dir / filename).resolve()

        # Path traversal guard
        if not str(target_path).startswith(str(tenant_dir)):
            raise ValueError("Target path traversal detected.")

        with open(target_path, "wb") as f:
            f.write(content)

        # Store relative path to allow environment relocations
        relative_path = str(target_path.relative_to(self.base_path)).replace("\\", "/")
        logger.info(
            "Document saved to storage",
            extra={
                "tenant_id": str(tenant_id),
                "file_id": str(file_id),
                "storage_path": relative_path,
                "bytes": len(content),
            },
        )
        return relative_path

    def _resolve_path(self, storage_path: str) -> Path:
        """Resolve storage path against base storage directory safely."""
        target_path = (self.base_path / storage_path).resolve()
        if not str(target_path).startswith(str(self.base_path)):
            raise ValueError(f"Storage path traversal detected: {storage_path}")
        return target_path

    def get_file(self, storage_path: str) -> bytes:
        """Read and return bytes from local storage path."""
        target_path = self._resolve_path(storage_path)
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"File not found in storage: {storage_path}")
        with open(target_path, "rb") as f:
            return f.read()

    def get_absolute_path(self, storage_path: str) -> Path:
        """Return absolute Path object for background workers/extractors."""
        target_path = self._resolve_path(storage_path)
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        return target_path

    def delete_file(self, storage_path: str) -> bool:
        """Delete file safely if exists."""
        try:
            target_path = self._resolve_path(storage_path)
            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                logger.info(f"Deleted storage file: {storage_path}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to delete storage file {storage_path}: {e}")
            return False


# Global singleton instance
_storage_service: Optional[BaseStorageService] = None


def get_storage_service() -> BaseStorageService:
    """Dependency provider for storage service."""
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service
