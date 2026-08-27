"""S3-compatible storage service — upload, download, signed URLs, delete."""

import logging
from typing import BinaryIO

from config import S3_BUCKET, S3_REGION, S3_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

logger = logging.getLogger(__name__)

_s3_client = None


def _get_s3_client():
    """Get or create S3 client. Returns None if not configured."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    if not S3_BUCKET or not AWS_ACCESS_KEY_ID:
        logger.info("S3 not configured — file storage disabled")
        return None

    try:
        import boto3
        kwargs = {
            "region_name": S3_REGION,
            "aws_access_key_id": AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
        }
        if S3_ENDPOINT:
            kwargs["endpoint_url"] = S3_ENDPOINT

        _s3_client = boto3.client("s3", **kwargs)
        logger.info("S3 client initialized for bucket %s", S3_BUCKET)
        return _s3_client
    except Exception as e:
        logger.error("Failed to initialize S3 client: %s", e)
        return None


async def upload_file(
    key: str,
    file_obj: BinaryIO,
    content_type: str = "application/octet-stream",
) -> str | None:
    """Upload a file to S3. Returns the key on success."""
    client = _get_s3_client()
    if not client:
        return None

    try:
        client.upload_fileobj(
            file_obj,
            S3_BUCKET,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded %s to S3", key)
        return key
    except Exception as e:
        logger.error("S3 upload failed for %s: %s", key, e)
        return None


async def download_file(key: str) -> bytes | None:
    """Download a file from S3. Returns bytes or None."""
    client = _get_s3_client()
    if not client:
        return None

    try:
        from io import BytesIO
        buf = BytesIO()
        client.download_fileobj(S3_BUCKET, key, buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error("S3 download failed for %s: %s", key, e)
        return None


async def generate_signed_url(key: str, expires_in: int = 3600) -> str | None:
    """Generate a presigned download URL. Expires in seconds."""
    client = _get_s3_client()
    if not client:
        return None

    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as e:
        logger.error("S3 presigned URL failed for %s: %s", key, e)
        return None


async def delete_file(key: str) -> bool:
    """Delete a file from S3."""
    client = _get_s3_client()
    if not client:
        return False

    try:
        client.delete_object(Bucket=S3_BUCKET, Key=key)
        logger.info("Deleted %s from S3", key)
        return True
    except Exception as e:
        logger.error("S3 delete failed for %s: %s", key, e)
        return False


def is_configured() -> bool:
    """Check if S3 storage is configured."""
    return bool(S3_BUCKET and AWS_ACCESS_KEY_ID)
