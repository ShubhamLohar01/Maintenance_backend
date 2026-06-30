"""Minimal S3 object storage for proof photos (machine transfers, etc.).

Uploads bytes to the configured bucket and returns the object's URL. Read access
to that URL depends on the bucket's policy (the existing complaint-module-images
bucket already serves images for the complaint module)."""
import boto3

from .config import settings

# allowed image content types -> file extension
_ALLOWED_IMAGE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}


def image_ext_for(content_type: str | None) -> str | None:
    """Return 'jpg'/'png' for an allowed image content-type, else None."""
    return _ALLOWED_IMAGE.get((content_type or "").strip().lower())


def _client():
    return boto3.client(
        "s3",
        region_name=settings.aws_region or None,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    """Put `data` at `key` in the configured bucket; return the object URL.

    Raises RuntimeError if no bucket is configured. Any boto3/network error
    propagates to the caller (the route is transactional, so the DB row is not
    committed if the upload fails)."""
    bucket = settings.aws_s3_bucket_name
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET_NAME is not configured")
    _client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return f"https://{bucket}.s3.{settings.aws_region}.amazonaws.com/{key}"
