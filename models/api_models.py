from pydantic import BaseModel
from typing import Optional, Any

# 번역 API 모델들
class TranslateRequest(BaseModel):
    text: str
    fromLanguage: str
    toLanguage: str

class TranslateData(BaseModel):
    translatedText: str
    originalText: str
    fromLanguage: str
    toLanguage: str

class ApiError(BaseModel):
    code: str
    message: str

class TranslateResponse(BaseModel):
    success: bool
    data: Optional[TranslateData] = None
    error: Optional[ApiError] = None

# 공통 응답 모델
class BaseResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[ApiError] = None 