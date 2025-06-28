from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import logging

from models.api_models import (
    WelcomeMessageRequest, WelcomeMessageResponse, WelcomeMessageData,
    ChatResponseRequest, ChatResponseResponse, ChatResponseData,
    ApiError
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