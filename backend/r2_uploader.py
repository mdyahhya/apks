import os
import sys
import logging
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.config import config

logger = logging.getLogger("R2Uploader")


class R2Uploader:
    def __init__(self):
        self._s3_client = None

    def get_client(self):
        """Create or return existing S3 boto3 client for Cloudflare R2."""
        if not config.is_r2_configured:
            raise ValueError(
                "Cloudflare R2 is not fully configured. Please set R2_ACCOUNT_ID, "
                "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME in .env"
            )

        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ImportError(
                "boto3 is not installed. Please run: pip install boto3"
            )

        # R2 uses region 'auto'
        endpoint = config.r2_endpoint_url
        if not endpoint and config.r2_account_id:
            endpoint = f"https://{config.r2_account_id}.r2.cloudflarestorage.com"

        s3_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30
        )

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=config.r2_access_key_id,
            aws_secret_access_key=config.r2_secret_access_key,
            region_name="auto",
            config=s3_config
        )
        return client

    def test_connection(self) -> dict:
        """Test authentication and bucket availability."""
        if not config.is_r2_configured:
            return {
                "success": False,
                "error": "Missing R2 credentials. Please configure .env file."
            }

        try:
            client = self.get_client()
            # Test listing or head bucket
            client.head_bucket(Bucket=config.r2_bucket_name)
            return {"success": True, "message": f"Successfully connected to bucket '{config.r2_bucket_name}'."}
        except Exception as e:
            error_str = str(e)
            if "403" in error_str or "Forbidden" in error_str or "InvalidAccessKeyId" in error_str:
                return {"success": False, "error": "Authentication failed: Invalid Access Key ID or Secret."}
            elif "404" in error_str or "NoSuchBucket" in error_str:
                return {"success": False, "error": f"Bucket '{config.r2_bucket_name}' does not exist in your Cloudflare R2 account."}
            elif "Could not connect" in error_str or "ConnectionError" in error_str:
                return {"success": False, "error": "Network error: Unable to connect to Cloudflare R2. Check your internet connection."}
            return {"success": False, "error": f"R2 Connection Error: {error_str}"}

    def upload_apk(self, file_path: str, metadata: dict) -> dict:
        """
        Upload APK to Cloudflare R2 with cache-control and APK MIME type.
        """
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"File does not exist: {file_path}"}

        try:
            client = self.get_client()
        except Exception as e:
            return {"success": False, "error": str(e)}

        object_key = config.r2_object_key or "latest/app-release.apk"
        bucket = config.r2_bucket_name

        # Prepare S3 extra arguments with Cache-Control headers
        extra_args = {
            "ContentType": "application/vnd.android.package-archive",
            "CacheControl": "no-cache, no-store, must-revalidate, max-age=0",
            "Metadata": {
                "version": str(metadata.get("version", "1.0.0")),
                "build": str(metadata.get("build_number", "")),
                "sha256": str(metadata.get("sha256", "")),
                "uploaded_at": datetime.now().isoformat()
            }
        }

        try:
            # Upload file
            with open(path, "rb") as file_data:
                client.put_object(
                    Bucket=bucket,
                    Key=object_key,
                    Body=file_data,
                    **extra_args
                )

            download_url = config.get_download_url()
            return {
                "success": True,
                "bucket": bucket,
                "object_key": object_key,
                "download_url": download_url,
                "uploaded_at": datetime.now().isoformat(),
                "uploaded_at_formatted": datetime.now().strftime("%d %b %Y, %I:%M %p")
            }

        except Exception as e:
            error_str = str(e)
            logger.error(f"Failed to upload APK to R2: {error_str}")
            if "EndpointConnectionError" in error_str or "Could not connect" in error_str:
                return {"success": False, "error": "Internet connection unavailable. Upload queued.", "is_offline": True}
            elif "403" in error_str or "Forbidden" in error_str:
                return {"success": False, "error": "R2 Access Denied: Check R2 API Token permissions (needs Object Read & Write)."}
            return {"success": False, "error": f"Upload failed: {error_str}"}


uploader = R2Uploader()
r2_uploader = uploader
