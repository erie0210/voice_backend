from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
import logging

from models.api_models import TranslateRequest, TranslateResponse, TranslateData, ApiError
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

@router.post("/translate", response_model=TranslateResponse)
async def translate_text(
    request: TranslateRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    텍스트를 지정된 언어로 번역합니다.
    """
    try:
        logger.info(f"번역 요청: {request.text[:50]}... ({request.fromLanguage} -> {request.toLanguage})")
        
        # OpenAI를 사용하여 번역 수행
        translated_text = await openai_service.translate_text(
            text=request.text,
            from_language=request.fromLanguage,
            to_language=request.toLanguage
        )
        
        logger.info(f"번역 완료: {translated_text[:50]}...")
        
        return TranslateResponse(
            success=True,
            data=TranslateData(
                translatedText=translated_text,
                originalText=request.text,
                fromLanguage=request.fromLanguage,
                toLanguage=request.toLanguage
            )
        )
        
    except Exception as e:
        logger.error(f"번역 오류: {str(e)}")
        
        return TranslateResponse(
            success=False,
            error=ApiError(
                code="TRANSLATION_ERROR",
                message=f"번역 중 오류가 발생했습니다: {str(e)}"
            )
        )

@router.post("/validate-key")
async def validate_openai_key():
    """
    OpenAI API 키의 유효성을 확인합니다.
    """
    try:
        is_valid = await openai_service.test_api_key()
        
        return {
            "success": True,
            "data": {
                "isValid": is_valid,
                "usage": {
                    "totalTokens": 0,  # 실제 사용량 추적이 필요하면 구현
                    "remainingTokens": 10000  # 예시 값
                }
            }
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"API 키 검증 중 오류가 발생했습니다: {str(e)}"
            }
        } 