#!/usr/bin/env python3
"""
Conversation Starters 음성 파일 생성 및 R2 업로드 스크립트

사용법:
    python scripts/generate_audio.py
"""
import asyncio
import json
import hashlib
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import logging

# 프로젝트 루트 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent.parent))

from services.openai_service import OpenAIService
from services.r2_service import R2Service
from models.api_models import TopicEnum, ReactionCategory, EmotionCategory

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AudioGenerator:
    def __init__(self):
        self.openai_service = OpenAIService()
        self.r2_service = R2Service()
        self.assets_path = Path(__file__).parent.parent / "assets" / "conversation_starters"
        self.chat_responses_path = Path(__file__).parent.parent / "assets" / "chat_responses"
        
        # 지원 언어 (음성 생성 대상)
        self.target_languages = ["English", "Spanish", "Chinese", "Korean"]
        
        # 언어별 OpenAI TTS 모델 voice 매핑
        self.voice_mapping = {
            "English": "alloy",
            "Spanish": "nova", 
            "Chinese": "shimmer",
            "Korean": "onyx"
        }
        
        # 생성된 파일 메타데이터 저장용
        self.metadata = {}
    
    def _get_text_hash(self, text: str) -> str:
        """텍스트의 해시값을 생성합니다."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
    
    def _get_audio_file_path(self, category: str, from_lang: str, to_lang: str, index: int, text_hash: str) -> str:
        """R2에 저장될 오디오 파일 경로를 생성합니다."""
        return f"conversation_starters/{category}/{from_lang}_{to_lang}/{index}_{text_hash}.mp3"
    
    async def _check_file_exists(self, file_path: str) -> bool:
        """R2에 파일이 이미 존재하는지 확인합니다."""
        try:
            await self.r2_service.head_object(file_path)
            return True
        except Exception:
            return False
    
    async def _generate_and_upload_audio(self, text: str, language: str, file_path: str) -> Tuple[bool, str]:
        """
        텍스트를 음성으로 변환하고 R2에 업로드합니다.
        
        Returns:
            Tuple[bool, str]: (성공 여부, 파일 URL 또는 에러 메시지)
        """
        try:
            # OpenAI TTS로 음성 생성
            logger.info(f"음성 생성 중: {text[:50]}... ({language})")
            
            # voice 선택
            voice = self.voice_mapping.get(language, "alloy")
            
            # 임시 파일로 음성 생성
            temp_file_path = f"/tmp/temp_audio_{hashlib.md5(text.encode()).hexdigest()}.mp3"
            
            # OpenAI TTS API 호출
            response = self.openai_service.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text
            )
            
            # 임시 파일에 저장
            with open(temp_file_path, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            
            logger.info(f"음성 파일 생성 완료: {temp_file_path}")
            
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
                file_url = f"https://voice-assets.ekfrl.site/{file_path}"
                logger.info(f"R2 업로드 성공: {file_url}")
                return True, file_url
            else:
                logger.error(f"R2 업로드 실패: {file_path}")
                return False, "R2 업로드 실패"
                
        except Exception as e:
            logger.error(f"음성 생성/업로드 오류: {str(e)}")
            return False, str(e)
    
    async def process_greetings(self) -> Dict[str, Dict[str, List[str]]]:
        """greetings.json의 모든 텍스트를 음성으로 변환합니다."""
        logger.info("=== 인사말 음성 생성 시작 ===")
        
        greetings_file = self.assets_path / "greetings.json"
        
        try:
            with open(greetings_file, 'r', encoding='utf-8') as f:
                greetings_data = json.load(f)
        except Exception as e:
            logger.error(f"greetings.json 로드 실패: {str(e)}")
            return {}
        
        results = {}
        
        for from_lang, to_langs in greetings_data.items():
            results[from_lang] = {}
            
            for to_lang, texts in to_langs.items():
                if to_lang not in self.target_languages:
                    logger.info(f"스킵: {to_lang} (대상 언어 아님)")
                    continue
                
                results[from_lang][to_lang] = []
                
                for index, text in enumerate(texts):
                    text_hash = self._get_text_hash(text)
                    file_path = self._get_audio_file_path("greetings", from_lang, to_lang, index, text_hash)
                    
                    # 이미 존재하는지 확인
                    if await self._check_file_exists(file_path):
                        file_url = f"https://voice-assets.ekfrl.site/{file_path}"
                        logger.info(f"기존 파일 사용: {file_url}")
                        results[from_lang][to_lang].append(file_url)
                        continue
                    
                    # 새로 생성
                    success, result = await self._generate_and_upload_audio(text, to_lang, file_path)
                    
                    if success:
                        results[from_lang][to_lang].append(result)
                    else:
                        logger.error(f"음성 생성 실패: {text[:50]}... - {result}")
                        results[from_lang][to_lang].append(None)
                    
                    # API 호출 제한을 위한 잠시 대기
                    await asyncio.sleep(1)
        
        return results
    
    async def process_topics(self) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
        """topics/*.json의 모든 텍스트를 음성으로 변환합니다."""
        logger.info("=== 주제별 대화 시작 문장 음성 생성 시작 ===")
        
        topics = ["favorites", "feelings", "ootd"]
        results = {}
        
        for topic in topics:
            topic_file = self.assets_path / "topics" / f"{topic}.json"
            
            try:
                with open(topic_file, 'r', encoding='utf-8') as f:
                    topic_data = json.load(f)
            except Exception as e:
                logger.error(f"{topic}.json 로드 실패: {str(e)}")
                continue
            
            results[topic] = {}
            
            for from_lang, to_langs in topic_data.items():
                results[topic][from_lang] = {}
                
                for to_lang, texts in to_langs.items():
                    if to_lang not in self.target_languages:
                        logger.info(f"스킵: {to_lang} (대상 언어 아님)")
                        continue
                    
                    results[topic][from_lang][to_lang] = []
                    
                    for index, text in enumerate(texts):
                        text_hash = self._get_text_hash(text)
                        file_path = self._get_audio_file_path(f"topics/{topic}", from_lang, to_lang, index, text_hash)
                        
                        # 이미 존재하는지 확인
                        if await self._check_file_exists(file_path):
                            file_url = f"https://voice-assets.ekfrl.site/{file_path}"
                            logger.info(f"기존 파일 사용: {file_url}")
                            results[topic][from_lang][to_lang].append(file_url)
                            continue
                        
                        # 새로 생성
                        success, result = await self._generate_and_upload_audio(text, to_lang, file_path)
                        
                        if success:
                            results[topic][from_lang][to_lang].append(result)
                        else:
                            logger.error(f"음성 생성 실패: {text[:50]}... - {result}")
                            results[topic][from_lang][to_lang].append(None)
                        
                        # API 호출 제한을 위한 잠시 대기
                        await asyncio.sleep(1)
        
        return results
    
    async def process_reactions(self) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
        """reactions/*.json의 모든 텍스트를 음성으로 변환합니다."""
        logger.info("=== 반응 카테고리 음성 생성 시작 ===")
        
        # 반응 카테고리별 파일명 매핑
        reaction_files = {
            "empathy": "empathy.json",
            "acceptance": "acceptance.json",
            "surprise": "surprise.json",
            "comfort": "comfort.json",
            "joy_sharing": "joy_sharing.json",
            "confirmation": "confirmation.json",
            "slow_questioning": "slow_questioning.json"
        }
        
        results = {}
        
        for reaction_name, filename in reaction_files.items():
            reaction_file = self.chat_responses_path / "reactions" / filename
            
            try:
                with open(reaction_file, 'r', encoding='utf-8') as f:
                    reaction_data = json.load(f)
            except Exception as e:
                logger.error(f"{filename} 로드 실패: {str(e)}")
                continue
            
            results[reaction_name] = {}
            
            for from_lang, to_langs in reaction_data.items():
                results[reaction_name][from_lang] = {}
                
                for to_lang, texts in to_langs.items():
                    if to_lang not in self.target_languages:
                        logger.info(f"스킵: {to_lang} (대상 언어 아님)")
                        continue
                    
                    results[reaction_name][from_lang][to_lang] = []
                    
                    for index, text in enumerate(texts):
                        text_hash = self._get_text_hash(text)
                        file_path = self._get_audio_file_path(f"reactions/{reaction_name}", from_lang, to_lang, index, text_hash)
                        
                        # 이미 존재하는지 확인
                        if await self._check_file_exists(file_path):
                            file_url = f"https://voice-assets.ekfrl.site/{file_path}"
                            logger.info(f"기존 파일 사용: {file_url}")
                            results[reaction_name][from_lang][to_lang].append(file_url)
                            continue
                        
                        # 새로 생성
                        success, result = await self._generate_and_upload_audio(text, to_lang, file_path)
                        
                        if success:
                            results[reaction_name][from_lang][to_lang].append(result)
                        else:
                            logger.error(f"음성 생성 실패: {text[:50]}... - {result}")
                            results[reaction_name][from_lang][to_lang].append(None)
                        
                        # API 호출 제한을 위한 잠시 대기
                        await asyncio.sleep(1)
        
        return results
    
    async def process_emotions(self) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
        """emotions/*.json의 모든 텍스트를 음성으로 변환합니다."""
        logger.info("=== 감정 카테고리 음성 생성 시작 ===")
        
        # 감정 카테고리별 파일명 매핑
        emotion_files = {
            "happy": "happy.json",
            "sad": "sad.json",
            "angry": "angry.json",
            "scared": "scared.json",
            "shy": "shy.json",
            "sleepy": "sleepy.json",
            "upset": "upset.json",
            "confused": "confused.json",
            "bored": "bored.json",
            "love": "love.json",
            "proud": "proud.json",
            "nervous": "nervous.json"
        }
        
        results = {}
        
        for emotion_name, filename in emotion_files.items():
            emotion_file = self.chat_responses_path / "emotions" / filename
            
            try:
                with open(emotion_file, 'r', encoding='utf-8') as f:
                    emotion_data = json.load(f)
            except Exception as e:
                logger.error(f"{filename} 로드 실패: {str(e)}")
                continue
            
            results[emotion_name] = {}
            
            for from_lang, to_langs in emotion_data.items():
                results[emotion_name][from_lang] = {}
                
                for to_lang, texts in to_langs.items():
                    if to_lang not in self.target_languages:
                        logger.info(f"스킵: {to_lang} (대상 언어 아님)")
                        continue
                    
                    results[emotion_name][from_lang][to_lang] = []
                    
                    for index, text in enumerate(texts):
                        text_hash = self._get_text_hash(text)
                        file_path = self._get_audio_file_path(f"emotions/{emotion_name}", from_lang, to_lang, index, text_hash)
                        
                        # 이미 존재하는지 확인
                        if await self._check_file_exists(file_path):
                            file_url = f"https://voice-assets.ekfrl.site/{file_path}"
                            logger.info(f"기존 파일 사용: {file_url}")
                            results[emotion_name][from_lang][to_lang].append(file_url)
                            continue
                        
                        # 새로 생성
                        success, result = await self._generate_and_upload_audio(text, to_lang, file_path)
                        
                        if success:
                            results[emotion_name][from_lang][to_lang].append(result)
                        else:
                            logger.error(f"음성 생성 실패: {text[:50]}... - {result}")
                            results[emotion_name][from_lang][to_lang].append(None)
                        
                        # API 호출 제한을 위한 잠시 대기
                        await asyncio.sleep(1)
        
        return results
    
    async def save_metadata(self, greetings_results: Dict, topics_results: Dict, reactions_results: Dict = None, emotions_results: Dict = None):
        """생성된 음성 파일 메타데이터를 저장합니다."""
        metadata = {
            "greetings": greetings_results,
            "topics": topics_results,
            "generated_at": str(asyncio.get_event_loop().time()),
            "target_languages": self.target_languages
        }
        
        # 반응 결과가 있으면 추가
        if reactions_results:
            metadata["reactions"] = reactions_results
            
        # 감정 결과가 있으면 추가
        if emotions_results:
            metadata["emotions"] = emotions_results
        
        # 로컬에 메타데이터 저장
        metadata_file = self.assets_path / "audio_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # R2에도 업로드
        metadata_content = json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
        await self.r2_service.upload_file(
            file_content=metadata_content,
            file_path="conversation_starters/audio_metadata.json",
            content_type="application/json"
        )
        
        logger.info("메타데이터 저장 완료")
    
    async def run(self):
        """전체 음성 생성 프로세스를 실행합니다."""
        logger.info("🎙️ Conversation Starters & Chat Responses 음성 생성 시작")
        logger.info(f"대상 언어: {', '.join(self.target_languages)}")
        
        try:
            # 1. 인사말 음성 생성
            greetings_results = await self.process_greetings()
            
            # 2. 주제별 대화 시작 문장 음성 생성  
            topics_results = await self.process_topics()
            
            # 3. 반응 카테고리 음성 생성
            reactions_results = await self.process_reactions()
            
            # 4. 감정 카테고리 음성 생성
            emotions_results = await self.process_emotions()
            
            # 5. 메타데이터 저장
            await self.save_metadata(greetings_results, topics_results, reactions_results, emotions_results)
            
            logger.info("✅ 모든 음성 생성 완료!")
            
            # 결과 요약
            total_greetings = sum(len(to_langs.get(lang, [])) for to_langs in greetings_results.values() 
                                for lang in self.target_languages if lang in to_langs)
            total_topics = sum(len(lang_data.get(lang, [])) for topic_data in topics_results.values() 
                             for lang_data in topic_data.values() for lang in self.target_languages if lang in lang_data)
            total_reactions = sum(len(lang_data.get(lang, [])) for reaction_data in reactions_results.values() 
                                for lang_data in reaction_data.values() for lang in self.target_languages if lang in lang_data)
            total_emotions = sum(len(lang_data.get(lang, [])) for emotion_data in emotions_results.values() 
                               for lang_data in emotion_data.values() for lang in self.target_languages if lang in lang_data)
            
            logger.info(f"📊 생성 결과:")
            logger.info(f"   - 인사말 음성 파일: {total_greetings}개")
            logger.info(f"   - 주제별 음성 파일: {total_topics}개")
            logger.info(f"   - 반응 음성 파일: {total_reactions}개")
            logger.info(f"   - 감정 음성 파일: {total_emotions}개")
            logger.info(f"   - 총 음성 파일: {total_greetings + total_topics + total_reactions + total_emotions}개")
            
        except Exception as e:
            logger.error(f"❌ 음성 생성 중 오류 발생: {str(e)}")
            raise

async def main():
    """메인 함수"""
    generator = AudioGenerator()
    await generator.run()

if __name__ == "__main__":
    asyncio.run(main()) 