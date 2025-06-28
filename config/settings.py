import os
from typing import Optional

class Settings:
    # OpenAI 설정
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_DEFAULT_MODEL: str = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
    
    # API 인증 설정
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "easyslang-api-secret-key-2024")
    
    # 서버 설정
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    
    # Railway 환경 변수
    RAILWAY_ENVIRONMENT: Optional[str] = os.getenv("RAILWAY_ENVIRONMENT")
    
    # Cloudflare R2 관련 환경변수
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "9bbeb5fd21af8c4c9b4badb59cb00120")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "3acb21d179a5485a19d525ce8118af4701cee45ea661ed3eaf4c5671ab37a5cb")
    R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "7ad7a2be1b222d45fad2d7336cda164b")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "ekfrl-voice")
    R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "https://voice.kreators.dev")
    
    def __init__(self):
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")

settings = Settings() 