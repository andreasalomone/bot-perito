# app/services/storage/cleanup_s3_job.py
import logging
import os
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv  # Per esecuzione locale

# Carica variabili d'ambiente da .env se presente (utile per esecuzione locale)
# Assicurati che lo script sia eseguito dalla root del progetto o che .env sia nel CWD.
# Per Render, le env var saranno settate direttamente.
dotenv_path = os.path.join(os.path.dirname(__file__), "../../../.env")  # Vai su 3 livelli e poi a .env
load_dotenv(dotenv_path=dotenv_path)

# Configura il logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Leggi la configurazione dalle variabili d'ambiente
# Le impostazioni da app.core.config non sono usate qui per rendere lo script più standalone
# e facilmente eseguibile come un task separato.
AWS_ACCESS_KEY_ID_CLEANUP = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY_CLEANUP = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION_CLEANUP = os.getenv("AWS_REGION", "eu-north-1")
S3_BUCKET_NAME_CLEANUP = os.getenv("S3_BUCKET_NAME")
# Il prefisso "uploads/" è una convenzione per dove vengono caricati i file temporanei
S3_CLEANUP_PREFIX = os.getenv("S3_CLEANUP_PREFIX", "uploads/")
# TTL per i file su S3 (in ore), default a 240 ore. Dovrebbe corrispondere
# a settings.s3_cleanup_max_age_hours se vuoi consistenza, ma qui è indipendente.
S3_MAX_AGE_HOURS_CLEANUP = int(os.getenv("S3_MAX_AGE_HOURS", "240"))


def get_s3_client_for_cleanup() -> Any | None:
    if not all([AWS_ACCESS_KEY_ID_CLEANUP, AWS_SECRET_ACCESS_KEY_CLEANUP, S3_BUCKET_NAME_CLEANUP, AWS_REGION_CLEANUP]):
        logger.error("AWS S3 credentials, bucket name, or region not configured for cleanup job. Exiting.")
        return None

    try:
        session = boto3.session.Session(
            aws_access_key_id=AWS_ACCESS_KEY_ID_CLEANUP,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY_CLEANUP,
            region_name=AWS_REGION_CLEANUP,
        )
        s3 = session.client("s3")
        logger.info(f"S3 client for cleanup initialized for bucket: {S3_BUCKET_NAME_CLEANUP} in region: {AWS_REGION_CLEANUP}")
        return s3
    except Exception as e:
        logger.error(f"Failed to initialize S3 client for cleanup: {e}", exc_info=True)
        return None


def run_s3_cleanup() -> None:
    s3 = get_s3_client_for_cleanup()
    if not s3 or not S3_BUCKET_NAME_CLEANUP:
        return

    logger.info(f"Starting S3 cleanup for prefix '{S3_CLEANUP_PREFIX}' in bucket '{S3_BUCKET_NAME_CLEANUP}'.")
    logger.info(f"Objects older than {S3_MAX_AGE_HOURS_CLEANUP} hours will be deleted.")

    cutoff_time = datetime.now(UTC) - timedelta(hours=S3_MAX_AGE_HOURS_CLEANUP)
    objects_to_delete = []
    deleted_count = 0
    scanned_count = 0

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME_CLEANUP, Prefix=S3_CLEANUP_PREFIX):
            if "Contents" not in page:
                continue

            for obj in page["Contents"]:
                scanned_count += 1
                obj_key = obj["Key"]
                # Ignora le "pseudo-cartelle" (oggetti che finiscono con / e hanno dimensione 0)
                if obj_key.endswith("/") and obj.get("Size", 0) == 0:
                    continue

                last_modified_aware = obj["LastModified"].replace(tzinfo=UTC)  # Assicura che sia timezone-aware
                if last_modified_aware < cutoff_time:
                    objects_to_delete.append({"Key": obj_key})
                    logger.info(f"Marked for deletion: {obj_key} (Last Modified: {last_modified_aware})")

                # S3 delete_objects può gestire fino a 1000 oggetti per volta
                if len(objects_to_delete) >= 1000:
                    s3.delete_objects(Bucket=S3_BUCKET_NAME_CLEANUP, Delete={"Objects": objects_to_delete})
                    deleted_count += len(objects_to_delete)
                    logger.info(f"Deleted batch of {len(objects_to_delete)} objects.")
                    objects_to_delete = []

        # Elimina eventuali oggetti rimanenti
        if objects_to_delete:
            s3.delete_objects(Bucket=S3_BUCKET_NAME_CLEANUP, Delete={"Objects": objects_to_delete})
            deleted_count += len(objects_to_delete)
            logger.info(f"Deleted final batch of {len(objects_to_delete)} objects.")

        logger.info(f"S3 Cleanup complete. Scanned {scanned_count} objects. Deleted {deleted_count} objects.")

    except ClientError as e:
        logger.error(f"ClientError during S3 cleanup: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred during S3 cleanup: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("Running S3 cleanup script directly...")
    run_s3_cleanup()
    logger.info("S3 cleanup script finished.")
