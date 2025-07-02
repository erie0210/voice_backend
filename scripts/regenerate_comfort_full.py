#!/usr/bin/env python3
"""
Comfort 카테고리 전체를 여성 목소리로 재생성하는 스크립트
"""
import asyncio
import json
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

class ComfortRegenerator:
    def __init__(self):
        self.openai_service = OpenAIService()
        self.r2_service = R2Service()
        self.chat_responses_path = Path(__file__).parent.parent / "assets" / "chat_responses"
    
    def _get_text_hash(self, text: str) -> str:
        """텍스트의 해시값을 생성합니다."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
    
    async def _generate_and_upload_audio(self, text: str, file_path: str) -> tuple[bool, str]:
        """
        텍스트를 여성 목소리 음성으로 변환하고 R2에 업로드합니다.
        """
        try:
            logger.info(f"음성 생성 중 (여성 목소리): {text}")
            
            # 임시 파일로 음성 생성
            temp_file_path = f"/tmp/temp_comfort_{hashlib.md5(text.encode()).hexdigest()}.mp3"
            
            # OpenAI TTS API 호출 (nova = 여성 목소리)
            response = self.openai_service.client.audio.speech.create(
                model="tts-1",
                voice="nova",  # 여성 목소리로 고정
                input=text
            )
            
            # 임시 파일에 저장
            with open(temp_file_path, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            
            # 파일 크기 확인
            file_size = os.path.getsize(temp_file_path)
            logger.info(f"음성 파일 생성 완료: {temp_file_path} ({file_size} bytes)")
            
            # R2에 업로드
            with open(temp_file_path, "rb") as f:
                file_content = f.read()
            
            upload_result = await self.r2_service.upload_file(
                file_content=file_content,
                file_path=file_path,
                content_type="audio/mpeg"
            )
            
            # 임시 파일 삭제
            os.remove(temp_file_path)
            
            if upload_result:
                file_url = f"https://voice.kreators.dev/{file_path}"
                logger.info(f"R2 업로드 성공: {file_url}")
                return True, file_url
            else:
                logger.error(f"R2 업로드 실패: {file_path}")
                return False, "R2 업로드 실패"
                
        except Exception as e:
            logger.error(f"음성 생성/업로드 오류: {str(e)}")
            return False, str(e)
    
    async def regenerate_all_comfort_audio(self):
        """comfort 카테고리의 모든 음성을 여성 목소리로 재생성합니다."""
        logger.info("=== Comfort 카테고리 전체 음성 재생성 시작 (여성 목소리) ===")
        
        comfort_file = self.chat_responses_path / "reactions" / "comfort.json"
        
        try:
            with open(comfort_file, 'r', encoding='utf-8') as f:
                comfort_data = json.load(f)
        except Exception as e:
            logger.error(f"comfort.json 로드 실패: {str(e)}")
            return
        
        results = []
        total_files = 0
        success_count = 0
        
        for from_lang, to_langs in comfort_data.items():
            for to_lang, texts in to_langs.items():
                logger.info(f"처리 중: {from_lang} -> {to_lang}")
                total_files += len(texts)
                
                for index, text in enumerate(texts):
                    text_hash = self._get_text_hash(text)
                    file_path = f"conversation_starters/reactions/comfort/{from_lang}_{to_lang}/{index}_{text_hash}.mp3"
                    
                    logger.info(f"파일 {index}: {text} -> {text_hash}")
                    
                    # 강제로 새로 생성 (기존 파일 무시)
                    success, result = await self._generate_and_upload_audio(text, file_path)
                    
                    if success:
                        results.append(result)
                        success_count += 1
                        logger.info(f"✅ 생성 성공 ({success_count}/{total_files}): {text}")
                    else:
                        logger.error(f"❌ 생성 실패: {text} - {result}")
                    
                    # API 호출 제한을 위한 잠시 대기
                    await asyncio.sleep(1.5)
        
        logger.info(f"=== Comfort 카테고리 재생성 완료! ===")
        logger.info(f"총 {total_files}개 파일 중 {success_count}개 성공")
        
        # 생성된 파일 URL 목록 출력
        logger.info("생성된 파일 목록:")
        for i, url in enumerate(results):
            logger.info(f"  {i}: {url}")
        
        return results

async def main():
    regenerator = ComfortRegenerator()
    await regenerator.regenerate_all_comfort_audio()

if __name__ == "__main__":
    asyncio.run(main()) 