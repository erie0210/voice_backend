import boto3
import logging
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)

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

class R2Service:
    """Cloudflare R2 스토리지 서비스 클래스"""
    
    def __init__(self):
        self.client = get_r2_client()
        self.bucket = settings.R2_BUCKET_NAME
        self.public_url = settings.R2_PUBLIC_URL
    
    async def upload_file(self, file_content: bytes, file_path: str, content_type: str = "application/octet-stream") -> bool:
        """
        파일을 R2에 업로드합니다.
        
        Args:
            file_content: 업로드할 파일 내용 (bytes)
            file_path: R2에 저장될 파일 경로
            content_type: 파일의 MIME 타입
            
        Returns:
            bool: 업로드 성공 여부
        """
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=file_path,
                Body=file_content,
                ContentType=content_type
            )
            logger.info(f"R2 업로드 성공: {file_path}")
            return True
        except Exception as e:
            logger.error(f"R2 업로드 실패: {file_path} - {str(e)}")
            return False
    
    async def head_object(self, file_path: str) -> dict:
        """
        파일의 메타데이터를 확인합니다. 파일이 존재하지 않으면 예외가 발생합니다.
        
        Args:
            file_path: 확인할 파일 경로
            
        Returns:
            dict: 파일 메타데이터
            
        Raises:
            Exception: 파일이 존재하지 않거나 접근 오류 시
        """
        return self.client.head_object(Bucket=self.bucket, Key=file_path)
    
    async def file_exists(self, file_path: str) -> bool:
        """
        파일이 존재하는지 확인합니다.
        
        Args:
            file_path: 확인할 파일 경로
            
        Returns:
            bool: 파일 존재 여부
        """
        try:
            await self.head_object(file_path)
            return True
        except Exception:
            return False
    
    def get_public_url(self, file_path: str) -> str:
        """
        파일의 공개 URL을 반환합니다.
        
        Args:
            file_path: 파일 경로
            
        Returns:
            str: 공개 URL
        """
        return f"{self.public_url}/{file_path}".replace("//", "/").replace(":/", "://")
    
    async def download_file(self, file_path: str) -> Optional[bytes]:
        """
        파일을 다운로드합니다.
        
        Args:
            file_path: 다운로드할 파일 경로
            
        Returns:
            bytes: 파일 내용 (실패 시 None)
        """
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=file_path)
            return response['Body'].read()
        except Exception as e:
            logger.error(f"R2 다운로드 실패: {file_path} - {str(e)}")
            return None 