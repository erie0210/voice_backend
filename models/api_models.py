from pydantic import BaseModel
from typing import Optional, Any, List
from datetime import datetime

# 공통 에러 모델
class ApiError(BaseModel):
    code: str
    message: str

# 공통 응답 모델
class BaseResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[ApiError] = None

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

class TranslateResponse(BaseModel):
    success: bool
    data: Optional[TranslateData] = None
    error: Optional[ApiError] = None

# 환영 메시지 API 모델들
class WelcomeMessageRequest(BaseModel):
    userLanguage: str
    aiLanguage: str
    difficultyLevel: str  # easy, intermediate, advanced
    userName: str

class WelcomeMessageData(BaseModel):
    message: str
    fallbackMessage: str

class WelcomeMessageResponse(BaseModel):
    success: bool
    data: Optional[WelcomeMessageData] = None
    error: Optional[ApiError] = None

# 채팅 메시지 모델
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    isUser: bool
    timestamp: datetime

# 채팅 응답 API 모델들
class ChatResponseRequest(BaseModel):
    messages: List[ChatMessage]
    userLanguage: str
    aiLanguage: str
    difficultyLevel: str
    lastUserMessage: str

class ChatResponseData(BaseModel):
    response: str
    practiceExpression: Optional[str] = None

class ChatResponseResponse(BaseModel):
    success: bool
    data: Optional[ChatResponseData] = None
    error: Optional[ApiError] = None

# TTS API 모델들
class TextToSpeechRequest(BaseModel):
    text: str
    language: str
    voice: Optional[str] = None

class TextToSpeechData(BaseModel):
    audioUrl: str
    audioData: Optional[str] = None  # base64 encoded audio data
    duration: float
    format: str = "mp3"

class TextToSpeechResponse(BaseModel):
    success: bool
    data: Optional[TextToSpeechData] = None
    error: Optional[ApiError] = None

# API 키 검증 모델들
class ValidateKeyRequest(BaseModel):
    apiKey: str

class UsageData(BaseModel):
    totalTokens: int
    remainingTokens: int

class ValidateKeyData(BaseModel):
    isValid: bool
    usage: UsageData

class ValidateKeyResponse(BaseModel):
    success: bool
    data: Optional[ValidateKeyData] = None
    error: Optional[ApiError] = None 