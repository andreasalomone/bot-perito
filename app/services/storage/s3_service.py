# app/services/storage/s3_service.py
import io
import logging

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings  # Importa la tua istanza di settings

logger = logging.getLogger(__name__)

# Controlla che le configurazioni necessarie siano presenti all'avvio del modulo
if not all([settings.aws_access_key_id, settings.aws_secret_access_key, settings.s3_bucket_name, settings.aws_region]):
    logger.error("AWS S3 credentials or bucket name/region not configured. S3_SERVICE WILL LIKELY FAIL.")
    # Potresti voler sollevare un'eccezione qui se S3 è critico per l'avvio
    # raise RuntimeError("S3 Service cannot be initialized due to missing configuration")
    _S3 = None
    _BUCKET = None
else:
    try:
        # La sessione può essere creata una volta e riutilizzata
        _SESSION = boto3.session.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        _S3 = _SESSION.client("s3", config=Config(signature_version="s3v4"))
        _BUCKET = settings.s3_bucket_name
        logger.info(f"S3 Service initialized for bucket: {_BUCKET} in region: {settings.aws_region}")
    except Exception as e:
        logger.error(f"Failed to initialize S3 session: {e}", exc_info=True)
        _S3 = None
        _BUCKET = None


def create_presigned_put(key: str, content_type: str, expires: int = 900) -> str | None:
    """
    Generates a presigned URL for uploading an object to S3.
    """
    if not _S3 or not _BUCKET:
        logger.error("S3 client not initialized. Cannot create presigned URL.")
        return None
    try:
        url = _S3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": _BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )
        logger.info(f"Generated presigned PUT URL for key: {key}")
        return url
    except ClientError as e:
        logger.error(f"Error generating presigned URL for key {key}: {e}", exc_info=True)
        return None


async def download_bytes(key: str) -> bytes | None:
    """
    Downloads an object from S3 as bytes.
    Note: This is a blocking operation made async by running in a thread elsewhere.
    """
    if not _S3 or not _BUCKET:
        logger.error("S3 client not initialized. Cannot download file.")
        return None

    buf = io.BytesIO()
    try:
        _S3.download_fileobj(_BUCKET, key, buf)
        buf.seek(0)
        logger.info(f"Successfully downloaded S3 object: {key}")
        return buf.read()
    except ClientError as e:
        logger.error(f"Error downloading S3 object {key}: {e}")
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.warning(f"File not found in S3: {_BUCKET}/{key}")
        else:
            logger.exception(f"ClientError downloading S3 object {key}")  # Log full trace for other ClientErrors
        return None
    except Exception:
        logger.exception(f"Unexpected error downloading S3 object {key}")
        return None
