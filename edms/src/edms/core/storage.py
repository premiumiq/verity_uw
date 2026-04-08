"""EDMS storage layer — MinIO/S3 operations.

Wraps the minio Python SDK to provide:
- upload_file: upload a local file to a bucket
- download_bytes: download a file's content as bytes
- upload_text: upload a string as a .txt file
- ensure_bucket: create a bucket if it doesn't exist

Uses storage_provider/container/key abstraction. Currently only
MinIO is implemented, but the interface supports S3 and Azure Blob
by swapping the client initialization.
"""

import io
from pathlib import Path

from minio import Minio


class StorageClient:
    """MinIO/S3 storage operations for EDMS."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ):
        """Initialize the MinIO client.

        Args:
            endpoint: MinIO server address (e.g., "minio:9000" or "localhost:9000")
            access_key: MinIO access key
            secret_key: MinIO secret key
            secure: Use HTTPS (False for local development)
        """
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Create a bucket if it doesn't exist."""
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def upload_file(self, bucket: str, key: str, file_path: str | Path) -> int:
        """Upload a local file to MinIO.

        Args:
            bucket: Bucket name (e.g., "submissions")
            key: Object key within the bucket (e.g., "sub-001/acord_855.pdf")
            file_path: Path to the local file

        Returns:
            File size in bytes.
        """
        file_path = Path(file_path)
        # Determine content type from extension
        content_type = _guess_content_type(file_path.suffix)
        file_size = file_path.stat().st_size

        self.client.fput_object(
            bucket, key, str(file_path),
            content_type=content_type,
        )
        return file_size

    def download_bytes(self, bucket: str, key: str) -> bytes:
        """Download a file's content as bytes.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            File content as bytes.
        """
        response = self.client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def upload_text(self, bucket: str, key: str, text: str) -> int:
        """Upload a string as a .txt file to MinIO.

        Used to save extracted text alongside the original document.

        Args:
            bucket: Bucket name
            key: Object key (e.g., "sub-001/acord_855.extracted.txt")
            text: Text content to upload

        Returns:
            Text size in bytes.
        """
        data = text.encode("utf-8")
        stream = io.BytesIO(data)
        self.client.put_object(
            bucket, key, stream, len(data),
            content_type="text/plain; charset=utf-8",
        )
        return len(data)

    def download_text(self, bucket: str, key: str) -> str:
        """Download a text file from MinIO and return as string."""
        data = self.download_bytes(bucket, key)
        return data.decode("utf-8")


def _guess_content_type(suffix: str) -> str:
    """Guess MIME type from file extension."""
    mapping = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".json": "application/json",
        ".csv": "text/csv",
        ".png": "image/png",
        ".jpg": "image/jpeg",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")
