import openai
import base64
import os
import random
import json
import time
import boto3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from config.settings import settings
from models.api_models import ChatMessage, LearnWord, TopicEnum
from services.r2_service import upload_file_to_r2

# 로깅 설정
logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # 기본 모델 설정 (설정 파일에서 가져옴)
        self.default_model = settings.OPENAI_DEFAULT_MODEL
        
        # AWS Polly 클라이언트 초기화 (폴백용)
        try:
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                self.polly_client = boto3.client(
                    'polly',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION
                )
            else:
                self.polly_client = None
                logger.warning("AWS 자격증명이 설정되지 않았습니다. Polly 폴백을 사용할 수 없습니다.")
        except Exception as e:
            self.polly_client = None
            logger.warning(f"AWS Polly 클라이언트 초기화 실패: {str(e)}")
        
        # 비용 최적화를 위한 캐시
        self._translation_cache: Dict[str, str] = {}
        self._api_key_cache: Dict[str, Dict] = {}
        self._welcome_message_cache: Dict[str, tuple] = {}
        
        # 캐시 만료 시간 (초)
        self.cache_expiry = 3600  # 1시간
        
        # OpenAI TTS 언어별 음성 설정
        self.voice_mapping = {
            "English": "alloy",
            "Spanish": "nova", 
            "Japanese": "shimmer",
            "Korean": "echo",
            "Chinese": "fable",
            "French": "onyx",
            "German": "alloy"
        }
        
        # AWS Polly 언어별 음성 설정 (폴백용)
        self.polly_voice_mapping = {
            "English": {"VoiceId": "Joanna", "LanguageCode": "en-US"},
            "Spanish": {"VoiceId": "Lucia", "LanguageCode": "es-ES"},
            "Japanese": {"VoiceId": "Mizuki", "LanguageCode": "ja-JP"},
            "Korean": {"VoiceId": "Seoyeon", "LanguageCode": "ko-KR"},
            "Chinese": {"VoiceId": "Zhiyu", "LanguageCode": "zh-CN"},
            "French": {"VoiceId": "Celine", "LanguageCode": "fr-FR"},
            "German": {"VoiceId": "Marlene", "LanguageCode": "de-DE"}
        }
        
        # 랜덤 주제 목록
        self.basic_topics = [
            "hobbies", "food", "travel", "family", "weather", "movies", 
            "music", "sports", "books", "pets", "work", "school"
        ]
        
        self.advanced_topics = [
            "culture", "technology", "environment", "philosophy", "art", 
            "science", "politics", "economics", "history", "psychology"
        ]
        
        # Assets 경로 설정
        self.assets_path = Path(__file__).parent.parent / "assets" / "conversation_starters"
        
        # 음성 파일 메타데이터 캐시
        self._audio_metadata = None
        self._metadata_loaded = False
    
    def _load_greetings_from_assets_by_language(self, user_language: str, ai_language: str) -> List[str]:
        """
        Assets 파일에서 특정 언어 조합의 인사말을 로드합니다.
        """
        try:
            greetings_file = self.assets_path / "greetings.json"
            if greetings_file.exists():
                with open(greetings_file, 'r', encoding='utf-8') as f:
                    all_greetings = json.load(f)
                    
                # from_{user_language} -> {ai_language} 경로로 찾기
                user_key = f"from_{user_language}"
                if user_key in all_greetings and ai_language in all_greetings[user_key]:
                    return all_greetings[user_key][ai_language]
                else:
                    logger.warning(f"언어 조합을 찾을 수 없음: {user_language} -> {ai_language}")
                    return self._get_fallback_greetings_for_languages(user_language, ai_language)
            else:
                logger.warning(f"Greetings 파일을 찾을 수 없습니다: {greetings_file}")
                return self._get_fallback_greetings_for_languages(user_language, ai_language)
        except Exception as e:
            logger.error(f"Greetings 파일 로드 오류: {str(e)}")
            return self._get_fallback_greetings_for_languages(user_language, ai_language)
    
    def _load_topic_starters_from_assets_by_language(self, topic: TopicEnum, user_language: str, ai_language: str) -> List[str]:
        """
        Assets 파일에서 특정 언어 조합의 주제별 대화 시작 문장을 로드합니다.
        """
        try:
            topic_files = {
                TopicEnum.FAVORITES: "favorites.json",
                TopicEnum.FEELINGS: "feelings.json", 
                TopicEnum.OOTD: "ootd.json"
            }
            
            filename = topic_files.get(topic, "favorites.json")
            topic_file = self.assets_path / "topics" / filename
            
            if topic_file.exists():
                with open(topic_file, 'r', encoding='utf-8') as f:
                    all_starters = json.load(f)
                    
                # from_{user_language} -> {ai_language} 경로로 찾기
                user_key = f"from_{user_language}"
                if user_key in all_starters and ai_language in all_starters[user_key]:
                    return all_starters[user_key][ai_language]
                else:
                    logger.warning(f"언어 조합을 찾을 수 없음: {user_language} -> {ai_language} for topic {topic.value}")
                    return self._get_fallback_topic_starters_for_languages(topic, user_language, ai_language)
            else:
                logger.warning(f"Topic 파일을 찾을 수 없습니다: {topic_file}")
                return self._get_fallback_topic_starters_for_languages(topic, user_language, ai_language)
        except Exception as e:
            logger.error(f"Topic 파일 로드 오류: {str(e)}")
            return self._get_fallback_topic_starters_for_languages(topic, user_language, ai_language)
    
    def _get_fallback_greetings_for_languages(self, user_language: str, ai_language: str) -> List[str]:
        """
        폴백용 기본 인사말 (언어 조합별)
        """
        if user_language == "Korean":
            if ai_language == "English":
                return ["Hello! 반가워! 😊 오늘도 English 공부해볼까?"]
            elif ai_language == "Spanish":
                return ["¡Hola! 반가워! 😊 오늘도 español 배워볼까?"]
            elif ai_language == "Japanese":
                return ["こんにちは! 반가워! 😊 오늘도 日本語 배워볼까?"]
            elif ai_language == "Chinese":
                return ["你好! 반가워! 😊 오늘도 中文 배워볼까?"]
            elif ai_language == "French":
                return ["Bonjour! 반가워! 😊 오늘도 français 배워볼까?"]
            elif ai_language == "German":
                return ["Hallo! 반가워! 😊 오늘도 Deutsch 배워볼까?"]
            else:
                return ["안녕하세요! 반가워요! 😊 오늘도 한국어 공부해볼까요?"]
        else:
            # 다른 언어에서 시작하는 경우 기본 형태
            return [f"Hello! Let's learn {ai_language} today! 😊"]
    
    def _get_fallback_topic_starters_for_languages(self, topic: TopicEnum, user_language: str, ai_language: str) -> List[str]:
        """
        폴백용 기본 주제 시작 문장 (언어 조합별)
        """
        topic_display = self._get_topic_display_name(topic)
        
        if user_language == "Korean":
            if ai_language == "English":
                return [f"Let's talk about {topic_display}! 😊"]
            elif ai_language == "Spanish":
                return [f"¡Hablemos sobre {topic_display}! 😊"]
            elif ai_language == "Japanese":
                return [f"{topic_display}について話しましょう！😊"]
            elif ai_language == "Chinese":
                return [f"我们来聊聊{topic_display}吧！😊"]
            elif ai_language == "French":
                return [f"Parlons de {topic_display}! 😊"]
            elif ai_language == "German":
                return [f"Lass uns über {topic_display} sprechen! 😊"]
            else:
                topic_korean = self._get_topic_korean_name(topic)
                return [f"{topic_korean}에 대해 얘기해봐요! 😊"]
        else:
            return [f"Let's talk about {topic_display}! 😊"]
    
    def _get_topic_display_name(self, topic: TopicEnum) -> str:
        """
        TopicEnum을 사용자에게 보여줄 텍스트로 변환합니다.
        """
        display_names = {
            TopicEnum.FAVORITES: "favorite things",
            TopicEnum.FEELINGS: "feelings",
            TopicEnum.OOTD: "outfit of the day"
        }
        return display_names.get(topic, topic.value.lower())
    
    def _get_topic_korean_name(self, topic: TopicEnum) -> str:
        """
        TopicEnum을 한국어 텍스트로 변환합니다.
        """
        korean_names = {
            TopicEnum.FAVORITES: "좋아하는 것들",
            TopicEnum.FEELINGS: "기분 표현",
            TopicEnum.OOTD: "오늘의 옷차림"
        }
        return korean_names.get(topic, topic.value)
    
    def _load_audio_metadata(self) -> None:
        """
        음성 파일 메타데이터를 로드합니다.
        """
        if self._metadata_loaded:
            return
            
        try:
            metadata_file = self.assets_path / "audio_metadata.json"
            if metadata_file.exists():
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    self._audio_metadata = json.load(f)
                logger.info("음성 파일 메타데이터 로드 완료")
            else:
                logger.warning("음성 파일 메타데이터를 찾을 수 없습니다. 첫 실행이거나 음성 생성이 필요합니다.")
                self._audio_metadata = {}
        except Exception as e:
            logger.error(f"음성 파일 메타데이터 로드 오류: {str(e)}")
            self._audio_metadata = {}
        finally:
            self._metadata_loaded = True
    
    def _get_text_hash(self, text: str) -> str:
        """텍스트의 해시값을 생성합니다."""
        import hashlib
        return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]
    
    def _find_audio_url_for_text(self, text: str, category: str, from_lang: str, to_lang: str) -> Optional[str]:
        """
        주어진 텍스트에 대응하는 음성 파일 URL을 찾습니다.
        
        Args:
            text: 찾을 텍스트
            category: 카테고리 ("greetings" 또는 "topics/favorites" 등)
            from_lang: 출발 언어
            to_lang: 대상 언어
            
        Returns:
            str: 음성 파일 URL (없으면 None)
        """
        self._load_audio_metadata()
        
        if not self._audio_metadata:
            return None
            
        try:
            # 카테고리별로 찾기
            if category == "greetings":
                metadata_section = self._audio_metadata.get("greetings", {})
            else:
                # topics의 경우 (e.g., "topics/favorites" -> "favorites")
                topic_name = category.split("/")[-1] if "/" in category else category
                metadata_section = self._audio_metadata.get("topics", {}).get(topic_name, {})
            
            # from_lang -> to_lang 경로로 찾기
            user_key = f"from_{from_lang}"
            if user_key not in metadata_section:
                return None
                
            lang_section = metadata_section[user_key].get(to_lang, [])
            
            # 텍스트 해시로 매칭 시도
            text_hash = self._get_text_hash(text)
            
            # URL에서 해시 추출하여 매칭
            for url in lang_section:
                if url and text_hash in url:
                    return url
            
            # 해시 매칭 실패 시 첫 번째 URL 반환 (fallback)
            if lang_section and len(lang_section) > 0:
                return lang_section[0]
                
            return None
            
        except Exception as e:
            logger.error(f"음성 URL 찾기 오류: {str(e)}")
            return None
    
    def _get_cache_key(self, *args) -> str:
        """캐시 키 생성"""
        return "_".join(str(arg) for arg in args)
    
    def _is_cache_valid(self, timestamp: float) -> bool:
        """캐시 유효성 검사"""
        return time.time() - timestamp < self.cache_expiry
    
    def _clear_expired_cache(self):
        """만료된 캐시 정리"""
        current_time = time.time()
        
        # 번역 캐시 정리
        expired_keys = [key for key, value in self._translation_cache.items() 
                       if isinstance(value, dict) and not self._is_cache_valid(value.get('timestamp', 0))]
        for key in expired_keys:
            del self._translation_cache[key]
        
        # API 키 캐시 정리
        expired_keys = [key for key, value in self._api_key_cache.items() 
                       if not self._is_cache_valid(value.get('timestamp', 0))]
        for key in expired_keys:
            del self._api_key_cache[key]
    
    def _detect_final_message(self, messages: List[ChatMessage], last_user_message: str) -> bool:
        """
        마지막 답변인지 감지합니다.
        시간 기반: 10분 이상 간격이 있으면 마지막 답변으로 처리
        키워드 기반: goodbye, bye, end, finish 등의 키워드 감지
        """
        try:
            # 키워드 기반 감지
            farewell_keywords = [
                'bye', 'goodbye', 'good bye', 'see you', 'end', 'finish', 'done', 'stop',
                '안녕', '잘가', '끝', '그만', '종료', '마침', '끝내',
                'さようなら', 'また明日', '終わり', '끦', 'adiós', 'au revoir', 'auf wiedersehen'
            ]
            
            user_message_lower = last_user_message.lower().strip()
            if any(keyword in user_message_lower for keyword in farewell_keywords):
                logger.info(f"키워드 기반 마지막 답변 감지: {last_user_message}")
                return True
            
            # 시간 기반 감지 (10분 = 600초)
            if len(messages) >= 2:
                current_time = datetime.now()
                last_message_time = messages[-1].timestamp
                time_gap = (current_time - last_message_time).total_seconds()
                
                if time_gap > 600:  # 10분 이상 간격
                    logger.info(f"시간 기반 마지막 답변 감지: {time_gap}초 간격")
                    return True
            
            # 대화 길이 기반 (20번 이상 대화 후 확률적으로 마지막 답변 처리)
            if len(messages) >= 20:
                import random
                if random.random() < 0.3:  # 30% 확률
                    logger.info(f"대화 길이 기반 마지막 답변 감지: {len(messages)}개 메시지")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"마지막 답변 감지 중 오류: {str(e)}")
            return False
    
    async def translate_text(self, text: str, from_language: str, to_language: str) -> str:
        """
        OpenAI를 사용하여 텍스트를 번역합니다. (캐싱 적용)
        """
        try:
            # 캐시 키 생성
            cache_key = self._get_cache_key(text, from_language, to_language)
            
            # 캐시된 번역이 있는지 확인
            if cache_key in self._translation_cache:
                cached_data = self._translation_cache[cache_key]
                if isinstance(cached_data, dict) and self._is_cache_valid(cached_data.get('timestamp', 0)):
                    return cached_data['translation']
            
            # 만료된 캐시 정리
            self._clear_expired_cache()
            
            # 번역 프롬프트 템플릿 (API 명세서 기준) - 간결화
            prompt = f"Translate from {from_language} to {to_language}: {text}"
            
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": f"You are a translator. Translate {from_language} to {to_language} accurately and concisely."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,  # 1000에서 300으로 대폭 감소
                temperature=0.1  # 0.3에서 0.1로 감소하여 일관성 향상 및 토큰 절약
            )
            
            translated_text = response.choices[0].message.content.strip()
            
            # 결과를 캐시에 저장
            self._translation_cache[cache_key] = {
                'translation': translated_text,
                'timestamp': time.time()
            }
            
            return translated_text
            
        except Exception as e:
            raise Exception(f"번역 중 오류가 발생했습니다: {str(e)}")
    
    async def generate_welcome_message(self, user_language: str, ai_language: str, 
                                     difficulty_level: str, user_name: str) -> tuple[str, str]:
        """
        환영 메시지를 생성합니다.
        """
        try:
            # 난이도에 따른 주제 선택
            if difficulty_level == "advanced":
                random_topic = random.choice(self.advanced_topics)
            else:
                random_topic = random.choice(self.basic_topics)
            
            # 시스템 지시 수정
            system_content ="""
- Begin instantly with a playful line or question about {random_topic}. (<30 words, 1 emoji)
- Return valid JSON

GOAL:
Break the ice by asking about the learner's day or their take on {random_topic}.

JSON FORMAT:
{{
  "message": "fun opener here",
  "fallback": "simple fallback (<20 words, no greetings)"
}}
"""

            
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=120,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            response_content = response.choices[0].message.content.strip()
            
            # JSON 파싱 시도
            try:
                parsed_response = json.loads(response_content)
                welcome_message = parsed_response.get("message", "")
                fallback_message = parsed_response.get("fallback", "")
                
                # 기본값 설정 (JSON 파싱 성공했지만 내용이 비어있는 경우)
                if not welcome_message:
                    welcome_message = f"Hi {user_name}! 😊 I'm MurMur, your AI teacher. Let's talk about {random_topic}!"
                if not fallback_message:
                    fallback_message = f"Hi {user_name}! 😊 Let's practice together!"
                    
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 기본 메시지 사용
                welcome_message = f"Hi {user_name}! 😊 I'm MurMur, your AI teacher. Let's talk about {random_topic}!"
                fallback_message = f"Hi {user_name}! 😊 Let's practice together!"
            
            return welcome_message, fallback_message
            
        except Exception as e:
            raise Exception(f"환영 메시지 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def generate_conversation_starters(self, user_language: str, ai_language: str, 
                                           topic: TopicEnum, difficulty_level: str) -> tuple[str, List[LearnWord], Optional[str]]:
        """
        주제와 언어에 맞는 대화 시작 문장을 20개 생성하고 그 중 하나를 랜덤 선택합니다.
        인사말과 함께 반환하며, 학습할 단어들과 음성 파일 URL도 함께 제공합니다.
        
        Returns:
            tuple: (conversation, learn_words, audio_url)
        """
        # 지원 언어 확인 (음성 파일이 있는 언어만)
        supported_audio_languages = ["English", "Spanish", "Chinese", "Korean"]
        
        # Assets에서 언어 조합별 인사말 로드
        greetings = self._load_greetings_from_assets_by_language(user_language, ai_language)
        
        try:
            # Assets에서 언어 조합별 주제별 대화 시작 문장 로드
            starters = self._load_topic_starters_from_assets_by_language(topic, user_language, ai_language)
            
            if not starters:
                logger.warning(f"언어 조합 {user_language} -> {ai_language}에 대한 시작 문장을 찾을 수 없음. 기본 문장 사용.")
                topic_display = self._get_topic_display_name(topic)
                starters = [f"Let's talk about {topic_display}! 😊"]
            
            # 랜덤하게 하나 선택
            selected_starter = random.choice(starters)
            logger.info(f"선택된 대화 시작 문장: {selected_starter}")
            
            # 인사말 선택 및 조합
            selected_greeting = random.choice(greetings)
            full_conversation = f"{selected_greeting} {selected_starter}"
            
            # 학습 단어 추출
            learn_words = self._extract_learn_words_from_starter(full_conversation, ai_language, user_language)
            
            # 음성 URL 찾기 (지원 언어인 경우만)
            audio_url = None
            if ai_language in supported_audio_languages:
                try:
                    # 전체 대화의 음성 파일 찾기 시도
                    audio_url = self._find_audio_url_for_text(
                        full_conversation, 
                        f"topics/{topic.value.lower()}", 
                        user_language, 
                        ai_language
                    )
                    
                    # 전체 대화의 음성이 없으면 인사말만 찾기
                    if not audio_url:
                        audio_url = self._find_audio_url_for_text(
                            selected_greeting,
                            "greetings",
                            user_language,
                            ai_language
                        )
                    
                    if audio_url:
                        logger.info(f"음성 파일 URL 찾음: {audio_url}")
                    else:
                        logger.warning(f"음성 파일을 찾을 수 없음: {user_language} -> {ai_language}")
                        
                except Exception as e:
                    logger.error(f"음성 파일 URL 찾기 오류: {str(e)}")
            else:
                logger.info(f"음성 파일 미지원 언어: {ai_language}")
            
            return full_conversation, learn_words, audio_url
            
        except Exception as e:
            logger.error(f"대화 시작 문장 생성 오류: {str(e)}")
            # 폴백: 기본 문장 사용
            greeting = "Hello! 😊"
            topic_display = self._get_topic_display_name(topic)
            starter = f"Let's talk about {topic_display}!"
            full_conversation = f"{greeting} {starter}"
            learn_words = self._extract_learn_words_from_starter(full_conversation, ai_language, user_language)
            return full_conversation, learn_words, None
    
    def _extract_learn_words_from_starter(self, conversation: str, ai_language: str, user_language: str) -> List[LearnWord]:
        """
        대화 시작 문장에서 학습할 수 있는 단어들을 추출합니다.
        """
        try:
            # 언어별 핵심 단어 및 표현 정의
            language_words = {
                "English": [
                    {"word": "Hello", "meaning": "안녕하세요", "pronunciation": "헬로우"},
                    {"word": "Nice", "meaning": "좋은, 멋진", "pronunciation": "나이스"},
                    {"word": "music", "meaning": "음악", "pronunciation": "뮤직"},
                    {"word": "favorite", "meaning": "가장 좋아하는", "pronunciation": "페이버릿"},
                    {"word": "hobby", "meaning": "취미", "pronunciation": "하비"},
                    {"word": "feeling", "meaning": "기분", "pronunciation": "필링"},
                    {"word": "wearing", "meaning": "입고 있는", "pronunciation": "웨어링"},
                    {"word": "style", "meaning": "스타일", "pronunciation": "스타일"}
                ],
                "Spanish": [
                    {"word": "¡Hola!", "meaning": "안녕하세요!", "pronunciation": "올라"},
                    {"word": "música", "meaning": "음악", "pronunciation": "무시카"},
                    {"word": "favorito", "meaning": "가장 좋아하는", "pronunciation": "파보리토"},
                    {"word": "escuchar", "meaning": "듣다", "pronunciation": "에스쿠차르"},
                    {"word": "sentir", "meaning": "느끼다", "pronunciation": "센티르"},
                    {"word": "llevar", "meaning": "입다, 가지고 다니다", "pronunciation": "예바르"},
                    {"word": "estilo", "meaning": "스타일", "pronunciation": "에스틸로"},
                    {"word": "gustar", "meaning": "좋아하다", "pronunciation": "구스타르"}
                ],
                "Japanese": [
                    {"word": "こんにちは", "meaning": "안녕하세요", "pronunciation": "곤니치와"},
                    {"word": "音楽", "meaning": "음악", "pronunciation": "온가쿠"},
                    {"word": "好き", "meaning": "좋아하는", "pronunciation": "스키"},
                    {"word": "聞く", "meaning": "듣다", "pronunciation": "키쿠"},
                    {"word": "気分", "meaning": "기분", "pronunciation": "키분"},
                    {"word": "着る", "meaning": "입다", "pronunciation": "키루"},
                    {"word": "スタイル", "meaning": "스타일", "pronunciation": "스타이루"},
                    {"word": "趣味", "meaning": "취미", "pronunciation": "슈미"}
                ],
                "Korean": [
                    {"word": "안녕하세요", "meaning": "Hello", "pronunciation": "annyeonghaseyo"},
                    {"word": "음악", "meaning": "music", "pronunciation": "eumak"},
                    {"word": "좋아하다", "meaning": "to like", "pronunciation": "johahada"},
                    {"word": "듣다", "meaning": "to listen", "pronunciation": "deutda"},
                    {"word": "기분", "meaning": "feeling", "pronunciation": "gibun"},
                    {"word": "입다", "meaning": "to wear", "pronunciation": "ipda"},
                    {"word": "스타일", "meaning": "style", "pronunciation": "seutail"},
                    {"word": "취미", "meaning": "hobby", "pronunciation": "chwimi"}
                ],
                "Chinese": [
                    {"word": "你好", "meaning": "안녕하세요", "pronunciation": "니하오"},
                    {"word": "音乐", "meaning": "음악", "pronunciation": "인위에"},
                    {"word": "喜欢", "meaning": "좋아하다", "pronunciation": "시환"},
                    {"word": "听", "meaning": "듣다", "pronunciation": "팅"},
                    {"word": "心情", "meaning": "기분", "pronunciation": "신칭"},
                    {"word": "穿", "meaning": "입다", "pronunciation": "촨"},
                    {"word": "风格", "meaning": "스타일", "pronunciation": "펑거"},
                    {"word": "爱好", "meaning": "취미", "pronunciation": "아이하오"}
                ],
                "French": [
                    {"word": "Bonjour", "meaning": "안녕하세요", "pronunciation": "봉주르"},
                    {"word": "musique", "meaning": "음악", "pronunciation": "뮈지크"},
                    {"word": "préféré", "meaning": "가장 좋아하는", "pronunciation": "프레페레"},
                    {"word": "écouter", "meaning": "듣다", "pronunciation": "에쿠테"},
                    {"word": "sentiment", "meaning": "기분", "pronunciation": "상티망"},
                    {"word": "porter", "meaning": "입다", "pronunciation": "포르테"},
                    {"word": "style", "meaning": "스타일", "pronunciation": "스틸"},
                    {"word": "passe-temps", "meaning": "취미", "pronunciation": "파스-땅"}
                ],
                "German": [
                    {"word": "Hallo", "meaning": "안녕하세요", "pronunciation": "할로"},
                    {"word": "Musik", "meaning": "음악", "pronunciation": "무지크"},
                    {"word": "Lieblings-", "meaning": "가장 좋아하는", "pronunciation": "립링스"},
                    {"word": "hören", "meaning": "듣다", "pronunciation": "회렌"},
                    {"word": "Gefühl", "meaning": "기분", "pronunciation": "게퓔"},
                    {"word": "tragen", "meaning": "입다", "pronunciation": "트라겐"},
                    {"word": "Stil", "meaning": "스타일", "pronunciation": "슈틸"},
                    {"word": "Hobby", "meaning": "취미", "pronunciation": "호비"}
                ]
            }
            
            # 해당 언어의 단어 목록 가져오기
            words_list = language_words.get(ai_language, language_words["English"])
            
            # 대화 문장에서 찾을 수 있는 단어들 추출
            learn_words = []
            conversation_lower = conversation.lower()
            
            for word_info in words_list:
                word = word_info["word"].lower()
                # 단어가 대화에 포함되어 있는지 확인
                if word in conversation_lower:
                    learn_word = LearnWord(
                        word=word_info["word"],
                        meaning=word_info["meaning"],
                        example=f"Example: {conversation[:50]}...",
                        pronunciation=word_info.get("pronunciation")
                    )
                    learn_words.append(learn_word)
            
            # 최소 2개의 학습 단어 보장
            if len(learn_words) < 2:
                # 부족한 경우 기본 단어들로 채움
                remaining_words = [w for w in words_list if w not in learn_words][:2-len(learn_words)]
                for word_info in remaining_words:
                    learn_word = LearnWord(
                        word=word_info["word"],
                        meaning=word_info["meaning"],
                        example=None,
                        pronunciation=word_info.get("pronunciation")
                    )
                    learn_words.append(learn_word)
            
            return learn_words[:3]  # 최대 3개까지만 반환
            
        except Exception as e:
            logger.error(f"학습 단어 추출 중 오류: {str(e)}")
            # 기본 학습 단어 반환
            return [
                LearnWord(word="Hello", meaning="안녕하세요", example=None, pronunciation="헬로우"),
                LearnWord(word="Good", meaning="좋은", example=None, pronunciation="굿")
            ]
    
    # _get_default_starters 메서드 제거됨 - assets 파일을 사용하도록 변경
    
    async def generate_chat_response(self, messages: List[ChatMessage], user_language: str, 
                                   ai_language: str, difficulty_level: str, last_user_message: str) -> tuple[str, List[LearnWord]]:
        """
        대화 응답을 생성하고 학습할 단어/표현을 함께 반환합니다.
        """
        # --- ai_language 기반 필터링 함수는 try 바깥에 정의 ---
        def is_target_language_word(word: str, ai_language: str) -> bool:
            if ai_language.lower() == "english":
                import re
                return bool(re.match(r'^[A-Za-z\s\'\-]+$', word.strip()))
            elif ai_language.lower() == "japanese":
                return any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9faf' for c in word)
            elif ai_language.lower() == "korean":
                return any('\uac00' <= c <= '\ud7af' for c in word)
            elif ai_language.lower() == "chinese":
                return any('\u4e00' <= c <= '\u9fff' for c in word)
            elif ai_language.lower() == "french":
                import re
                return bool(re.match(r'^[A-Za-zÀ-ÿ\s\'\-]+$', word.strip()))
            elif ai_language.lower() == "german":
                import re
                return bool(re.match(r'^[A-Za-zÄÖÜäöüß\s\'\-]+$', word.strip()))
            elif ai_language.lower() == "spanish":
                import re
                return bool(re.match(r'^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\'\-]+$', word.strip()))
            return True

        try:
            # 마지막 답변 감지 로직
            is_final_message = self._detect_final_message(messages, last_user_message)
            
            # 대화 히스토리를 OpenAI 형식으로 변환 (유저와 AI의 직전 답변 2개만 사용)
            chat_history = []
            for msg in messages[-2:]:  # 최근 2개 메시지만 사용 (유저 1개 + AI 1개)
                chat_history.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            # 레벨별 프롬프트 정의
            level_prompts = {
                "easy": f"""
- Reply in {user_language}; act like a native {ai_language} speaker who speaks {user_language} fluently
- UNDERSTAND by pronunciation, not exact meaning - if they try to say something, figure out what they meant
- PRAISE A LOT even for tiny attempts - be super encouraging like talking to a baby
- Use very simple words and encourage them to use easy expressions
- Take what they said in {user_language} and show them "You can say this in {ai_language}: [expression]"
- Give pronunciation tips and useful expressions
- Example: "와! 정말 잘했어요! 👏 '좋아해요'는 영어로 'I like it'이라고 해요. 발음은 '아이 라이크 잇'이에요!"
""",
                "intermediate": f"""
- Reply ONLY in {ai_language}; act like a very kind elementary school teacher (grades 1-3)
- Use elementary level {ai_language} with good native expressions that kids can learn
- Paraphrase the user's message into a more natural, native {ai_language} expression and show it
- Correct their expressions to better, more natural native phrases
- Explain simply and kindly, use easy words
- Focus on teaching good expressions children should know
""",
                "advanced": f"""
- Reply ONLY in {ai_language}; act like a native {ai_language} speaker at middle school level
- Paraphrase the user's message into a more sophisticated, native {ai_language} expression and show it
- Engage in deep discussions on various topics (culture, society, academics, etc.)
- Correct pronunciation, word order, and expressions to high-level native usage
- Use sophisticated expressions and help them use advanced vocabulary
- Challenge them with complex topics and nuanced language (up to 40 words)
"""
            }
            
            # 현재 레벨에 맞는 프롬프트 선택
            current_level_prompt = level_prompts.get(difficulty_level, level_prompts["easy"])
            
            # 레벨별 단어 수 제한
            word_limits = {
                "easy": "18-22 words",
                "intermediate": "18-22 words", 
                "advanced": "up to 40 words"
            }
            current_word_limit = word_limits.get(difficulty_level, "18-22 words")
            
            # 현재 사용되는 레벨 프롬프트 로깅
            logger.info(f"=== 선택된 레벨 프롬프트 ({difficulty_level.upper()}) ===")
            logger.info(f"프롬프트 내용:\n{current_level_prompt}")
            logger.info(f"단어 수 제한: {current_word_limit}")
            logger.info("=" * 50)
            
            # 마지막 답변일 때의 특별한 지시사항
            final_message_instruction = ""
            if is_final_message:
                final_message_instruction = f"""

⭐ FINAL MESSAGE SPECIAL INSTRUCTION ⭐
This seems like the end of our conversation. Please:
1) Praise their learning effort today with warm encouragement
2) Suggest reviewing what they learned (ask them to repeat key expressions)
3) Motivate them to continue studying {ai_language}
4) Give a cheerful farewell
5) Keep it warm and supportive - celebrate their progress!"""

            # 간소화된 시스템 프롬프트 (토큰 절약)
            system_prompt = f"""You are MurMur, language coach for {ai_language}.

SPECIAL: If user says "Hello, Start to Talk!": Brief intro + topic question.

STRUCTURE: 1) React to user 2) Teach 1 {ai_language} expression 3) Ask more

CURRENT LEVEL ({difficulty_level.upper()}):
{current_level_prompt}

LEARN WORDS: Always 2-3 items in {ai_language}. The expression taught must appear in learnWords.

RESPONSE LENGTH: {current_word_limit}{final_message_instruction}

Return valid JSON:
{{
  "response": "your actual response here",
  "learnWords": [{{"word":"example","meaning":"explanation","example":"usage","pronunciation":"phonetic"}}]
}}"""
            
            # 시스템 메시지 추가
            messages_for_api = [{"role": "system", "content": system_prompt}] + chat_history
            
            # 요청 파라미터 로깅
            logger.info(f"=== OpenAI API 요청 시작 ===")
            logger.info(f"모델: {self.default_model}")
            logger.info(f"메시지 개수: {len(messages_for_api)}")
            logger.info(f"시스템 프롬프트 길이: {len(system_prompt)}")
            logger.info(f"사용자 마지막 메시지: {last_user_message}")
            logger.info(f"난이도: {difficulty_level}, 언어: {user_language} -> {ai_language}")
            
            # 프롬프트 내용 상세 로깅
            for i, msg in enumerate(messages_for_api):
                logger.info(f"메시지 {i+1} ({msg['role']}): {msg['content'][:200]}...")
            
            try:
                logger.info("OpenAI API 호출 시작...")
                response = self.client.chat.completions.create(
                    model=self.default_model,
                    messages=messages_for_api,
                    max_tokens=300,  # 200에서 300으로 증가
                    temperature=0.7,
                    response_format={"type": "json_object"}  # JSON 형태 강제
                )
                logger.info("OpenAI API 호출 완료")
                
                # 응답 상세 정보 로깅
                logger.info(f"=== OpenAI API 응답 분석 ===")
                logger.info(f"응답 객체 타입: {type(response)}")
                
                if hasattr(response, 'choices') and response.choices:
                    logger.info(f"choices 개수: {len(response.choices)}")
                    choice = response.choices[0]
                    finish_reason = getattr(choice, 'finish_reason', 'N/A')
                    logger.info(f"첫 번째 choice finish_reason: {finish_reason}")
                    
                    # finish_reason이 length인 경우 특별 경고
                    if finish_reason == "length":
                        logger.warning("⚠️ 토큰 한계 도달! 응답이 잘렸을 수 있습니다. max_tokens 증가 필요.")
                    
                    if hasattr(choice, 'message'):
                        message = choice.message
                        logger.info(f"메시지 객체 타입: {type(message)}")
                        logger.info(f"메시지 role: {getattr(message, 'role', 'N/A')}")
                        content = getattr(message, 'content', None)
                        logger.info(f"메시지 content 타입: {type(content)}")
                        logger.info(f"메시지 content 값 (처음 200자): {repr(content[:200]) if content else 'None'}")
                    else:
                        logger.error("choice에 message 속성이 없음")
                else:
                    logger.error("응답에 choices가 없거나 비어있음")
                
                # 사용량 정보 로깅
                if hasattr(response, 'usage'):
                    usage = response.usage
                    prompt_tokens = getattr(usage, 'prompt_tokens', 'N/A')
                    completion_tokens = getattr(usage, 'completion_tokens', 'N/A')
                    total_tokens = getattr(usage, 'total_tokens', 'N/A')
                    logger.info(f"토큰 사용량 - prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}")
                    
                    # 프롬프트 토큰이 너무 많으면 경고
                    if isinstance(prompt_tokens, int) and prompt_tokens > 600:
                        logger.warning(f"⚠️ 프롬프트 토큰이 너무 많습니다 ({prompt_tokens}). 시스템 프롬프트나 대화 히스토리 단축 필요.")
                
            except Exception as api_error:
                logger.error(f"OpenAI API 호출 중 예외 발생: {type(api_error).__name__}: {str(api_error)}")
                raise api_error
            
            response_content = response.choices[0].message.content
            
            # 응답 내용 안전성 검사
            if response_content is None:
                logger.error("OpenAI 응답 content가 None입니다")
                response_content = ""
            else:
                response_content = response_content.strip()
                
                # 공백만 있는 응답 감지
                if not response_content:
                    logger.warning("OpenAI 응답이 공백/줄바꿈만 포함하고 있습니다 (토큰 부족 의심)")
            
            logger.info(f"OpenAI 응답 원본 (길이: {len(response_content)}): {response_content}")
            
            # JSON 응답 파싱
            try:
                parsed_response = json.loads(response_content)
                logger.info("JSON 파싱 성공")
                chat_response = parsed_response.get("response", "")
                learn_words_data = parsed_response.get("learnWords", [])
                
                logger.info(f"추출된 응답: {chat_response}")
                logger.info(f"추출된 학습단어 개수: {len(learn_words_data)}")
                
                # LearnWord 객체로 변환
                learn_words = []
                for word_data in learn_words_data:
                    learn_word = LearnWord(
                        word=word_data.get("word", ""),
                        meaning=word_data.get("meaning", ""),
                        example=word_data.get("example"),
                        pronunciation=word_data.get("pronunciation")
                    )
                    learn_words.append(learn_word)
                
                learn_words = [w for w in learn_words if is_target_language_word(w.word, ai_language)]
                logger.info(f"필터링 후 학습단어 개수: {len(learn_words)}")
                
                # 학습 단어가 비어있으면 기본 단어 추가
                if not learn_words and chat_response:
                    words = chat_response.split()
                    for word in words:
                        clean_word = ''.join(c for c in word if c.isalpha())
                        if len(clean_word) > 2 and is_target_language_word(clean_word, ai_language):
                            default_word = LearnWord(
                                word=clean_word,
                                meaning=f"({user_language}로) 의미를 찾아보세요",
                                example=None,
                                pronunciation=None
                            )
                            learn_words.append(default_word)
                            break
                    logger.info(f"기본 학습단어 추가 후 개수: {len(learn_words)}")
                
                return chat_response, learn_words
                
            except json.JSONDecodeError as e:
                # JSON 파싱 실패 시 더 상세한 로깅
                logger.error(f"JSON 파싱 실패 - 에러: {str(e)}")
                logger.error(f"JSON 파싱 실패 - 전체 응답 내용:\n{response_content}")
                logger.error(f"JSON 파싱 실패 - 응답 길이: {len(response_content)}")
                logger.error(f"JSON 파싱 실패 - 첫 100자: {response_content[:100]}")
                logger.error(f"JSON 파싱 실패 - 마지막 100자: {response_content[-100:]}")
                
                # 1. "response": "내용" 패턴 찾기 (개선된 정규식)
                import re
                response_patterns = [
                    r'"response"\s*:\s*"([^"]+(?:\\.[^"]*)*)"',  # 기본 패턴
                    r'"response"\s*:\s*"([^"]*[^\\])"',  # 이스케이프 문자 고려
                    r'response["\']?\s*:\s*["\']([^"\']+)["\']'  # 따옴표 변형 고려
                ]
                
                extracted_response = None
                for i, pattern in enumerate(response_patterns):
                    match = re.search(pattern, response_content, re.DOTALL)
                    if match:
                        extracted_response = match.group(1)
                        logger.info(f"정규식 패턴 {i+1}번으로 응답 추출 성공: {extracted_response[:100]}...")
                        break
                    else:
                        logger.debug(f"정규식 패턴 {i+1}번 실패")
                
                # 2. 패턴 매칭 실패 시, JSON 시작 부분에서 response 값 추출 시도
                if not extracted_response:
                    logger.warning("모든 정규식 패턴 실패, 직접 파싱 시도")
                    # {"response":"내용 형태에서 내용 부분만 추출
                    if response_content.startswith('{"response":"'):
                        start_idx = len('{"response":"')
                        content_part = response_content[start_idx:]
                        end_markers = ['"', "',", '",']
                        min_end = len(content_part)
                        for marker in end_markers:
                            end_idx = content_part.find(marker)
                            if end_idx != -1 and end_idx < min_end:
                                min_end = end_idx
                        
                        if min_end < len(content_part):
                            extracted_response = content_part[:min_end]
                            logger.info(f"직접 파싱으로 응답 추출 성공: {extracted_response[:100]}...")
                        else:
                            logger.warning("직접 파싱도 실패 - 종료 마커를 찾을 수 없음")
                    else:
                        logger.warning(f"직접 파싱 실패 - 예상된 시작 패턴이 없음. 실제 시작: {response_content[:50]}")
                
                if extracted_response:
                    logger.info(f"최종 추출된 응답: {extracted_response}")
                    
                    # 기본 학습 단어 생성
                    words = extracted_response.split()
                    default_learn_words = []
                    for word in words:
                        clean_word = ''.join(c for c in word if c.isalpha())
                        if len(clean_word) > 2 and is_target_language_word(clean_word, ai_language):
                            default_word = LearnWord(
                                word=clean_word,
                                meaning=f"({user_language}로) 의미를 찾아보세요",
                                example=None,
                                pronunciation=None
                            )
                            default_learn_words.append(default_word)
                            if len(default_learn_words) >= 2:  # 최대 2개까지
                                break
                    
                    logger.info(f"기본 학습단어 생성 완료: {len(default_learn_words)}개")
                    return extracted_response, default_learn_words
                else:
                    # 모든 추출 시도 실패
                    logger.error("모든 응답 추출 시도 실패 - 기본 응답으로 대체")
                    
                    clean_response = "죄송해요, 응답을 생성하는 중에 문제가 발생했어요. 다시 말씀해 주시겠어요? 😊"
                    
                    default_word = LearnWord(
                        word="문제",
                        meaning="어려운 상황이나 해결해야 할 일",
                        example="이 문제를 해결해야 합니다.",
                        pronunciation=None
                    )
                    
                    return clean_response, [default_word]
            
            # --- 추가 후처리: 응답이 greeting으로 시작하면 제거 ---
        except Exception as e:
            raise Exception(f"채팅 응답 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def _text_to_speech_polly(self, text: str, language: str) -> tuple[str, float]:
        """
        AWS Polly를 사용하여 텍스트를 음성으로 변환합니다. (폴백용)
        """
        if not self.polly_client:
            raise Exception("AWS Polly 클라이언트가 초기화되지 않았습니다.")
        
        try:
            # 언어에 따른 음성 선택
            voice_config = self.polly_voice_mapping.get(language, self.polly_voice_mapping["English"])
            
            response = self.polly_client.synthesize_speech(
                Text=text,
                OutputFormat='mp3',
                VoiceId=voice_config["VoiceId"],
                LanguageCode=voice_config["LanguageCode"]
            )
            
            # 임시 파일로 저장
            import tempfile
            
            timestamp = int(time.time())
            filename = f"polly_tts_{timestamp}.mp3"
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            
            # 오디오 데이터를 파일로 저장
            with open(temp_path, 'wb') as f:
                f.write(response['AudioStream'].read())
            
            # 파일 크기로 대략적인 재생 시간 계산
            file_size = os.path.getsize(temp_path)
            estimated_duration = file_size / 16000  # 대략적인 추정
            
            # Cloudflare R2에 업로드
            object_name = f"tts/{filename}"
            audio_url = upload_file_to_r2(temp_path, object_name)
            
            # 임시 파일 삭제
            os.remove(temp_path)
            
            logger.info(f"AWS Polly TTS 성공: {audio_url}")
            return audio_url, estimated_duration
            
        except Exception as e:
            logger.error(f"AWS Polly TTS 실패: {str(e)}")
            raise Exception(f"AWS Polly 음성 합성 중 오류가 발생했습니다: {str(e)}")

    async def text_to_speech(self, text: str, language: str, voice: Optional[str] = None) -> tuple[str, float]:
        """
        텍스트를 음성으로 변환하고 Cloudflare R2에 업로드합니다.
        OpenAI TTS 실패 시 AWS Polly를 폴백으로 사용합니다.
        """
        # 먼저 OpenAI TTS 시도
        try:
            logger.info(f"OpenAI TTS 시도: {text[:50]}...")
            
            # 언어에 따른 음성 선택
            selected_voice = voice or self.voice_mapping.get(language, "alloy")
            
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=selected_voice,
                input=text
            )
            
            # 임시 파일로 저장
            import tempfile
            
            timestamp = int(time.time())
            filename = f"openai_tts_{timestamp}.mp3"
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            
            # 오디오 데이터를 파일로 저장
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            
            # 파일 크기로 대략적인 재생 시간 계산 (대략적인 추정)
            file_size = os.path.getsize(temp_path)
            estimated_duration = file_size / 16000  # 대략적인 추정
            
            # Cloudflare R2에 업로드
            object_name = f"tts/{filename}"
            audio_url = upload_file_to_r2(temp_path, object_name)
            
            # 임시 파일 삭제
            os.remove(temp_path)
            
            logger.info(f"OpenAI TTS 성공: {audio_url}")
            return audio_url, estimated_duration
            
        except Exception as openai_error:
            logger.warning(f"OpenAI TTS 실패: {str(openai_error)}")
            
            # AWS Polly 폴백 시도
            if self.polly_client:
                try:
                    logger.info(f"AWS Polly 폴백 시도: {text[:50]}...")
                    return await self._text_to_speech_polly(text, language)
                except Exception as polly_error:
                    logger.error(f"AWS Polly 폴백도 실패: {str(polly_error)}")
                    raise Exception(f"모든 TTS 서비스 실패 - OpenAI: {str(openai_error)}, Polly: {str(polly_error)}")
            else:
                # Polly 클라이언트가 없으면 원래 OpenAI 오류 반환
                raise Exception(f"OpenAI TTS 실패하고 Polly 폴백을 사용할 수 없습니다: {str(openai_error)}")
    
    async def test_api_key(self) -> bool:
        """
        API 키가 유효한지 테스트합니다.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1  # 5에서 1로 감소 - 최소한의 토큰만 사용
            )
            return True
        except Exception:
            return False

# 전역 OpenAI 서비스 인스턴스
openai_service = OpenAIService() 