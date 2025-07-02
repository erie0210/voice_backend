#!/usr/bin/env python3
"""
특정 comfort 음성 파일을 여성 목소리로 재생성하는 스크립트
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path
import logging

# 프로젝트 루트 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent.parent))

from services.openai_service import OpenAIService
from services.r2_service import R2Service

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def regenerate_specific_comfort_file():
    """특정 comfort 파일을 재생성합니다."""
    openai_service = OpenAIService()
    r2_service = R2Service()
    
    # 문제가 된 특정 텍스트
    text = "속상했겠다~"
    
    logger.info(f"=== 특정 파일 재생성: {text} ===")
    
    try:
        # 텍스트 해시 계산
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
        logger.info(f"텍스트 해시: {text_hash}")
        
        # 파일 경로
        file_path = f"conversation_starters/reactions/comfort/from_Korean_Korean/1_{text_hash}.mp3"
        logger.info(f"파일 경로: {file_path}")
        
        # 임시 파일 경로
        temp_file_path = f"/tmp/temp_comfort_single_{text_hash}.mp3"
        
        # OpenAI TTS API 호출 (nova = 여성 목소리)
        logger.info("음성 생성 중 (여성 목소리)...")
        response = openai_service.client.audio.speech.create(
            model="tts-1",
            voice="nova",  # 여성 목소리로 고정
            input=text
        )
        
        # 임시 파일에 저장
        with open(temp_file_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
        
        logger.info(f"음성 파일 생성 완료: {temp_file_path}")
        
        # 파일 크기 확인
        file_size = os.path.getsize(temp_file_path)
        logger.info(f"생성된 파일 크기: {file_size} bytes")
        
        # R2에 업로드
        with open(temp_file_path, "rb") as f:
            file_content = f.read()
        
        upload_result = await r2_service.upload_file(
            file_content=file_content,
            file_path=file_path,
            content_type="audio/mpeg"
        )
        
        # 임시 파일 삭제
        os.remove(temp_file_path)
        
        if upload_result:
            file_url = f"https://voice.kreators.dev/{file_path}"
            logger.info(f"✅ R2 업로드 성공: {file_url}")
            logger.info(f"✅ 재생성 완료!")
            return file_url
        else:
            logger.error(f"❌ R2 업로드 실패: {file_path}")
            return None
            
    except Exception as e:
        logger.error(f"❌ 음성 생성/업로드 오류: {str(e)}")
        return None

if __name__ == "__main__":
    asyncio.run(regenerate_specific_comfort_file()) 