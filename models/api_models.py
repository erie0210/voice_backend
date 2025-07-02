from pydantic import BaseModel
from typing import Optional, Any, List
from datetime import datetime
from enum import Enum

# 주제 ENUM
class TopicEnum(str, Enum):
    FAVORITES = "FAVORITES"
    FEELINGS = "FEELINGS"
    OOTD = "OOTD"

class ReactionCategory(str, Enum):
    """AI 반응 카테고리 - 미리 TTS를 생성할 반응 유형들"""
    EMPATHY = "EMPATHY"                    # 🙋‍♀️ 공감
    ACCEPTANCE = "ACCEPTANCE"              # 🫶 수용
    SURPRISE = "SURPRISE"                  # 😮 놀람
    COMFORT = "COMFORT"                    # 😢 위로
    JOY_SHARING = "JOY_SHARING"           # 😊 기쁨 나눔
    CONFIRMATION = "CONFIRMATION"          # 🤔 확인/공명
    SLOW_QUESTIONING = "SLOW_QUESTIONING"  # 🐢 천천히 되물음

class EmotionCategory(str, Enum):
    """감정 카테고리 - 설명 및 확장용 템플릿"""
    HAPPY = "HAPPY"                        # 😄 기쁨
    SAD = "SAD"                            # 😢 슬픔
    ANGRY = "ANGRY"                        # 😠 화남
    SCARED = "SCARED"                      # 😨 무서움
    SHY = "SHY"                            # 😳 부끄러움
    SLEEPY = "SLEEPY"                      # 😴 졸림
    UPSET = "UPSET"                        # 😔 속상함
    CONFUSED = "CONFUSED"                  # 😵 혼란/당황
    BORED = "BORED"                        # 🥱 지루함
    LOVE = "LOVE"                          # 😍 좋아함
    PROUD = "PROUD"                        # 😎 자랑스러움
    NERVOUS = "NERVOUS"                    # 😬 긴장됨

class ContinuationCategory(str, Enum):
    """이야기 이어가기 카테고리 - 대화 연결용 템플릿"""
    EMOTION_EXPLORATION = "EMOTION_EXPLORATION"        # 감정 탐색 이어가기
    EMOTION_ACTION = "EMOTION_ACTION"                  # 🧩 감정+행동 연결
    EMOTION_LEARNING = "EMOTION_LEARNING"              # 📚 감정+표현 학습 연결
    QUESTION_EXPANSION = "QUESTION_EXPANSION"          # 💬 질문 확장
    ENCOURAGEMENT_FLOW = "ENCOURAGEMENT_FLOW"          # 🌟 격려 + 다음 흐름
    EMOTION_TRANSITION = "EMOTION_TRANSITION"          # 🌈 감정 전환 유도

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

# 학습 단어/표현 모델
class LearnWord(BaseModel):
    word: str  # 학습할 단어 또는 표현
    meaning: str  # 사용자 언어로 된 의미
    example: Optional[str] = None  # 예문 (선택사항)
    pronunciation: Optional[str] = None  # 발음 (선택사항)

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
    learnWords: List[LearnWord] = []  # 학습할 단어/표현 목록
    audioUrl: Optional[str] = None  # 음성 파일 URL (템플릿 기반 응답용)

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

# 대화 시작 API 모델들
class ConversationStartRequest(BaseModel):
    userLanguage: str  # 사용자의 모국어
    aiLanguage: str    # 학습할 언어
    topic: TopicEnum   # 주제: TopicEnum 사용
    difficultyLevel: str  # easy, intermediate, advanced

class ConversationStartData(BaseModel):
    conversation: str  # 생성된 대화 시작 문장 (인사말 + 본문)
    topic: TopicEnum  # 사용된 주제
    difficulty: str   # 난이도
    learnWords: List[LearnWord] = []  # 학습할 단어/표현 목록
    audioUrl: Optional[str] = None  # 음성 파일 URL

class ConversationStartResponse(BaseModel):
    success: bool
    data: Optional[ConversationStartData] = None
    error: Optional[ApiError] = None 