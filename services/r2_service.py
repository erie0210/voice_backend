import boto3
from config.settings import settings

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto"
    )

def upload_file_to_r2(local_path: str, object_name: str) -> str:
    client = get_r2_client()
    bucket = settings.R2_BUCKET_NAME
    client.upload_file(local_path, bucket, object_name)
    return f"{settings.R2_PUBLIC_URL}/{object_name}" 