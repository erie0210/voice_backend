import openai
import base64
import os
import random
import json
import time
import boto3
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from config.settings import settings
from models.api_models import ChatMessage, LearnWord
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
            
            # 단일 호출로 메인 메시지와 폴백 메시지 모두 생성
            prompt = f"""Generate a cheerful, engaging first message for a language learning app.

User's native language: {user_language}
Target learning language: {ai_language}
User name: {user_name}
Difficulty level: {difficulty_level}
Starting topic: {random_topic}

Requirements:
- Be welcoming and enthusiastic
- DO NOT introduce yourself or say 'I'm MurMur' or similar
- DO NOT use generic greetings like 'Hello' or 'Hi'
- Use appropriate emoji
- Keep under 30 words
- Start IMMEDIATELY with the given topic and ask a question
- Make conversation feel natural, fun, and engaging from the very first sentence

Return JSON format:
{{
    "message": "main welcome message here",
    "fallback": "simple English fallback message here (under 20 words)"
}}"""
            
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": "You are MurMur, a cheerful AI language teacher. Generate welcome messages in JSON format."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=120,  # 150에서 120으로 감소
                temperature=0.7
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
    
    async def generate_chat_response(self, messages: List[ChatMessage], user_language: str, 
                                   ai_language: str, difficulty_level: str, last_user_message: str) -> tuple[str, List[LearnWord]]:
        """
        대화 응답을 생성하고 학습할 단어/표현을 함께 반환합니다.
        """
        try:
            # 대화 히스토리를 OpenAI 형식으로 변환
            chat_history = []
            for msg in messages[-10:]:  # 최근 10개 메시지만 사용
                chat_history.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            # 대화 응답 생성 프롬프트 (JSON 형태로 응답 요청)
            system_prompt = f"""You are a language coach helping a user learn {ai_language}.

                CRITICAL LANGUAGE USAGE RULES:
                - User's native language: {user_language}
                - Target learning language: {ai_language}  
                - Current difficulty: {difficulty_level}

                DIFFICULTY-BASED LANGUAGE SELECTION:
                - easy: ALWAYS respond primarily in the user's native language. Only introduce simple target language words/phrases with native language explanations.
                - intermediate: ALWAYS respond primarily in the target language but use SIMPLE vocabulary only. Add native language hints when needed.
                - advanced: ALWAYS respond ONLY in the target language using natural, native expressions.

                Personality rules:
                - Always be cheerful, playful, and positive
                - Use fun emojis often (😊, 🎉, 🌟, 🤔, 🍕, etc.)
                - Make light jokes, puns, or give fun language facts
                - Encourage mistakes as part of learning
                - React naturally with surprise, humor, or empathy

                Learning Rules:
                1. ALWAYS recognize attempts to speak the target language
                2. Praise effort first, then provide gentle correction if needed
                3. When correcting, give clear tip and ask to repeat (only ONCE per phrase)
                4. Don't repeat the same correction more than once
                5. Keep conversations engaging with follow-up questions

                CONVERSATION LEADERSHIP RULES:
                - DO NOT greet, introduce yourself, or mention the user's name
                - DO NOT use any greetings like 'Hello', 'Hi', or 'Hey'
                - Start IMMEDIATELY with a topic, question, or interesting statement
                - After responding to user, ALWAYS suggest a new topic or ask an engaging question
                - Don't wait for users to bring up topics - be proactive
                - Mix topics between: daily life, interests, experiences, opinions, culture
                - Make smooth transitions between topics to keep conversation flowing
                - Example transitions: "By the way...", "Speaking of...", "I'm curious about...", "Let's talk about..."

                RESPONSE LENGTH CONSTRAINT:
                - Keep your conversational response between 18-20 words maximum
                - Be concise but engaging and natural
                - Prioritize key learning points over lengthy explanations

                CRITICAL LEARNING WORDS REQUIREMENT:
                - You MUST extract all learnWords ONLY from the target language ({ai_language}).
                - Do NOT include any words/expressions from the user's native language.
                - If you introduce a new phrase or idiom in {ai_language}, always include it in learnWords.
                - NEVER include greetings, introductions, or the user's name in your response or learnWords.
                - NEVER return an empty learnWords array

                CRITICAL JSON FORMAT REQUIREMENT:
                You MUST respond in valid JSON format ONLY. Do not include any text outside the JSON.
                
                Required JSON structure:
                {{
                    "response": "your conversational response here (18-20 words max)",
                    "learnWords": [
                        {{
                            "word": "학습할 단어나 표현 (MUST be in {ai_language})",
                            "meaning": "{user_language}로 된 의미 설명",
                            "example": "예문 (선택사항)",
                            "pronunciation": "발음 (선택사항)"
                        }}
                    ]
                }}

                Current difficulty: {difficulty_level}
                User's last message: "{last_user_message}"

                Respond ONLY with valid JSON. No additional text."""
            
            # 시스템 메시지 추가
            messages_for_api = [{"role": "system", "content": system_prompt}] + chat_history
            
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=messages_for_api,
                max_tokens=150,
                temperature=0.7,
                response_format={"type": "json_object"}  # JSON 형태 강제
            )
            
            response_content = response.choices[0].message.content.strip()
            
            # JSON 응답 파싱
            try:
                parsed_response = json.loads(response_content)
                chat_response = parsed_response.get("response", "")
                learn_words_data = parsed_response.get("learnWords", [])
                
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
                
                # --- ai_language 기반 필터링 ---
                def is_target_language_word(word: str, ai_language: str) -> bool:
                    if ai_language.lower() == "english":
                        # 영어: 알파벳/공백/기호만 허용
                        import re
                        return bool(re.match(r'^[A-Za-z\s\'\-]+$', word.strip()))
                    elif ai_language.lower() == "japanese":
                        # 일본어: 히라가나/가타카나/한자
                        return any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9faf' for c in word)
                    elif ai_language.lower() == "korean":
                        # 한글
                        return any('\uac00' <= c <= '\ud7af' for c in word)
                    elif ai_language.lower() == "chinese":
                        # 한자
                        return any('\u4e00' <= c <= '\u9fff' for c in word)
                    elif ai_language.lower() == "french":
                        # 프랑스어: 알파벳+악센트
                        import re
                        return bool(re.match(r'^[A-Za-zÀ-ÿ\s\'\-]+$', word.strip()))
                    elif ai_language.lower() == "german":
                        # 독일어: 알파벳+움라우트
                        import re
                        return bool(re.match(r'^[A-Za-zÄÖÜäöüß\s\'\-]+$', word.strip()))
                    elif ai_language.lower() == "spanish":
                        # 스페인어: 알파벳+악센트
                        import re
                        return bool(re.match(r'^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\'\-]+$', word.strip()))
                    return True  # 기타 언어는 필터링하지 않음
                
                learn_words = [w for w in learn_words if is_target_language_word(w.word, ai_language)]
                # --- END ai_language 기반 필터링 ---
                
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
                
                return chat_response, learn_words
                
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 텍스트에서 response 부분 추출 시도
                logger.warning(f"JSON 파싱 실패, 텍스트 추출 시도: {response_content[:100]}...")
                
                # "response": "내용" 패턴 찾기
                import re
                response_match = re.search(r'"response"\s*:\s*"([^"]+)"', response_content)
                
                if response_match:
                    extracted_response = response_match.group(1)
                    logger.info(f"응답 텍스트 추출 성공: {extracted_response}")
                    
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
                            break
                    
                    return extracted_response, default_learn_words
                else:
                    # 패턴 매칭 실패 시 전체 텍스트에서 JSON 부분 제거
                    logger.warning("응답 패턴 매칭 실패, 기본 응답 생성")
                    
                    # JSON 형태의 텍스트를 제거하고 깔끔한 응답 생성
                    clean_response = "죄송해요, 응답을 생성하는 중에 문제가 발생했어요. 다시 말씀해 주시겠어요? 😊"
                    
                    default_word = LearnWord(
                        word="문제",
                        meaning="어려운 상황이나 해결해야 할 일",
                        example="이 문제를 해결해야 합니다.",
                        pronunciation=None
                    )
                    
                    return clean_response, [default_word]
            
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