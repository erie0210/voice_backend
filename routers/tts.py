from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import logging

from models.api_models import (
    TextToSpeechRequest, TextToSpeechResponse, TextToSpeechData,
    ValidateKeyRequest, ValidateKeyResponse, ValidateKeyData, UsageData,
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

@router.post("/text-to-speech", response_model=TextToSpeechResponse)
async def text_to_speech(
    request: TextToSpeechRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    텍스트를 음성 파일로 변환합니다.
    """
    try:
        logger.info(f"TTS 요청: {request.text[:50]}... (언어: {request.language})")
        
        # OpenAI를 사용하여 TTS 생성
        audio_url, duration = await openai_service.text_to_speech(
            text=request.text,
            language=request.language,
            voice=request.voice
        )
        
        logger.info(f"TTS 생성 완료: {audio_url} (재생시간: {duration:.2f}초)")
        
        return TextToSpeechResponse(
            success=True,
            data=TextToSpeechData(
                audioUrl=audio_url,
                audioData=None,  # 필요시 base64 인코딩된 데이터 추가
                duration=duration,
                format="mp3"
            )
        )
        
    except Exception as e:
        logger.error(f"TTS 생성 오류: {str(e)}")
        
        return TextToSpeechResponse(
            success=False,
            error=ApiError(
                code="TTS_ERROR",
                message=f"음성 합성 중 오류가 발생했습니다: {str(e)}"
            )
        )

@router.post("/validate-key", response_model=ValidateKeyResponse)
async def validate_openai_key(request: ValidateKeyRequest):
    """
    OpenAI API 키의 유효성을 확인합니다.
    """
    try:
        logger.info("API 키 검증 요청")
        
        # 임시로 요청된 API 키를 사용하여 검증
        # 실제 구현에서는 보안상 이 방식은 권장하지 않음
        original_key = settings.OPENAI_API_KEY
        
        try:
            # 요청된 키로 임시 변경하여 테스트
            import openai
            test_client = openai.OpenAI(api_key=request.apiKey)
            
            response = test_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1
            )
            
            is_valid = True
            logger.info("API 키 검증 성공")
            
        except Exception as e:
            is_valid = False
            logger.warning(f"API 키 검증 실패: {str(e)}")
        
        return ValidateKeyResponse(
            success=True,
            data=ValidateKeyData(
                isValid=is_valid,
                usage=UsageData(
                    totalTokens=0,  # 실제 사용량 추적이 필요하면 구현
                    remainingTokens=10000 if is_valid else 0  # 예시 값
                )
            )
        )
        
    except Exception as e:
        logger.error(f"API 키 검증 오류: {str(e)}")
        
        return ValidateKeyResponse(
            success=False,
            error=ApiError(
                code="VALIDATION_ERROR",
                message=f"API 키 검증 중 오류가 발생했습니다: {str(e)}"
            )
        ) 