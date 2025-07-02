from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import logging

from models.api_models import (
    WelcomeMessageRequest, WelcomeMessageResponse, WelcomeMessageData,
    ChatResponseRequest, ChatResponseResponse, ChatResponseData,
    ConversationStartRequest, ConversationStartResponse, ConversationStartData,
    TopicEnum, ApiError
)
from services.openai_service import openai_service
from config.settings import settings

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

async def verify_api_key(authorization: Optional[str] = Header(None)):
    """
    API 키 인증을 검증합니다.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Authorization header가 누락되었습니다."}}
        )
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Bearer 토큰 형식이 올바르지 않습니다."}}
        )
    
    api_key = authorization.replace("Bearer ", "")
    
    # 간단한 API 키 검증 (실제 운영시에는 더 강화된 검증 필요)
    if api_key != settings.API_SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "API 키가 유효하지 않습니다."}}
        )
    
    return api_key

@router.post("/welcome-message", response_model=WelcomeMessageResponse)
async def generate_welcome_message(
    request: WelcomeMessageRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    언어 학습 앱의 첫 인사말을 생성합니다.
    """
    try:
        logger.info(f"환영 메시지 생성 요청: {request.userName} ({request.userLanguage} -> {request.aiLanguage}, {request.difficultyLevel})")
        
        # OpenAI를 사용하여 환영 메시지 생성
        welcome_message, fallback_message = await openai_service.generate_welcome_message(
            user_language=request.userLanguage,
            ai_language=request.aiLanguage,
            difficulty_level=request.difficultyLevel,
            user_name=request.userName
        )
        
        logger.info(f"환영 메시지 생성 완료: {welcome_message[:50]}...")
        
        return WelcomeMessageResponse(
            success=True,
            data=WelcomeMessageData(
                message=welcome_message,
                fallbackMessage=fallback_message
            )
        )
        
    except Exception as e:
        logger.error(f"환영 메시지 생성 오류: {str(e)}")
        
        return WelcomeMessageResponse(
            success=False,
            error=ApiError(
                code="WELCOME_MESSAGE_ERROR",
                message=f"환영 메시지 생성 중 오류가 발생했습니다: {str(e)}"
            )
        )

@router.post("/chat-response", response_model=ChatResponseResponse)
async def generate_chat_response(
    request: ChatResponseRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    사용자 메시지에 대한 AI 응답을 생성합니다.
    """
    try:
        logger.info(f"채팅 응답 생성 요청: {request.lastUserMessage[:50]}... ({request.userLanguage} -> {request.aiLanguage}, {request.difficultyLevel})")
        
        # OpenAI를 사용하여 채팅 응답 생성 (응답과 학습 단어 함께 받음)
        chat_response, learn_words = await openai_service.generate_chat_response(
            messages=request.messages,
            user_language=request.userLanguage,
            ai_language=request.aiLanguage,
            difficulty_level=request.difficultyLevel,
            last_user_message=request.lastUserMessage
        )
        
        logger.info(f"채팅 응답 생성 완료: {chat_response[:50]}... (학습 단어 {len(learn_words)}개)")
        
        return ChatResponseResponse(
            success=True,
            data=ChatResponseData(
                response=chat_response,
                practiceExpression=None,  # 필요시 추후 구현
                learnWords=learn_words
            )
        )
        
    except Exception as e:
        logger.error(f"채팅 응답 생성 오류: {str(e)}")
        
        return ChatResponseResponse(
            success=False,
            error=ApiError(
                code="CHAT_RESPONSE_ERROR",
                message=f"채팅 응답 생성 중 오류가 발생했습니다: {str(e)}"
            )
        )

@router.post("/conversation-start", response_model=ConversationStartResponse)
async def generate_conversation_start(
    request: ConversationStartRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    대화를 시작할 때 사용할 첫 문장을 생성합니다.
    주제와 언어에 맞는 20개의 문장 중 랜덤하게 하나를 선택하여 반환합니다.
    """
    try:
        logger.info(f"대화 시작 문장 생성 요청: {request.topic.value} ({request.userLanguage} -> {request.aiLanguage}, {request.difficultyLevel})")
        
        # 지원하는 언어 검증
        supported_languages = ["English", "Spanish", "Japanese", "Korean", "Chinese", "French", "German"]
        if request.aiLanguage not in supported_languages:
            return ConversationStartResponse(
                success=False,
                error=ApiError(
                    code="UNSUPPORTED_LANGUAGE",
                    message=f"지원하지 않는 언어입니다. 지원 언어: {', '.join(supported_languages)}"
                )
            )
        
        # TopicEnum 사용으로 자동 검증됨 (Pydantic이 처리)
        
        # OpenAI를 사용하여 대화 시작 문장 생성 (음성 URL 포함)
        conversation_starter, learn_words, audio_url = await openai_service.generate_conversation_starters(
            user_language=request.userLanguage,
            ai_language=request.aiLanguage,
            topic=request.topic,
            difficulty_level=request.difficultyLevel
        )
        
        audio_status = "있음" if audio_url else "없음"
        logger.info(f"대화 시작 문장 생성 완료: {conversation_starter[:50]}... (학습 단어 {len(learn_words)}개, 음성 {audio_status})")
        
        return ConversationStartResponse(
            success=True,
            data=ConversationStartData(
                conversation=conversation_starter,
                topic=request.topic,
                difficulty=request.difficultyLevel,
                learnWords=learn_words,
                audioUrl=audio_url
            )
        )
        
    except Exception as e:
        logger.error(f"대화 시작 문장 생성 오류: {str(e)}")
        
        return ConversationStartResponse(
            success=False,
            error=ApiError(
                code="CONVERSATION_START_ERROR",
                message=f"대화 시작 문장 생성 중 오류가 발생했습니다: {str(e)}"
            )
        ) 