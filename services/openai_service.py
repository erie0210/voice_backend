import openai
import base64
import os
import random
import json
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from config.settings import settings
from models.api_models import ChatMessage, LearnWord
from services.r2_service import upload_file_to_r2

class OpenAIService:
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # 기본 모델 설정 (설정 파일에서 가져옴)
        self.default_model = settings.OPENAI_DEFAULT_MODEL
        
        # 비용 최적화를 위한 캐시
        self._translation_cache: Dict[str, str] = {}
        self._api_key_cache: Dict[str, Dict] = {}
        self._welcome_message_cache: Dict[str, tuple] = {}
        
        # 캐시 만료 시간 (초)
        self.cache_expiry = 3600  # 1시간
        
        # 언어별 음성 설정
        self.voice_mapping = {
            "English": "alloy",
            "Spanish": "nova", 
            "Japanese": "shimmer",
            "Korean": "echo",
            "Chinese": "fable",
            "French": "onyx",
            "German": "alloy"
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
            prompt = f"""Generate a welcome message for a language learning app in JSON format:

User's native language: {user_language}
Target learning language: {ai_language}
User name: {user_name}
Difficulty level: {difficulty_level}
Starting topic: {random_topic}

Difficulty Rules:
- easy: Respond primarily in {user_language}. Use simple {ai_language} words with {user_language} explanations
- intermediate: Respond primarily in {ai_language} but use SIMPLE vocabulary only
- advanced: Speak naturally in {ai_language} only, use native expressions

Requirements:
1. Be welcoming and enthusiastic
2. Introduce yourself as MurMur AI teacher  
3. Use appropriate emoji
4. Keep under 30 words
5. Start with the given topic and ask a question
6. Make conversation feel natural and fun

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
                - YOU must always lead the conversation by introducing topics first
                - After responding to user, ALWAYS suggest a new topic or ask an engaging question
                - Don't wait for users to bring up topics - be proactive
                - Mix topics between: daily life, interests, experiences, opinions, culture
                - Make smooth transitions between topics to keep conversation flowing
                - Example transitions: "By the way...", "Speaking of...", "I'm curious about...", "Let's talk about..."

                RESPONSE LENGTH CONSTRAINT:
                - Keep your conversational response between 18-20 words maximum
                - Be concise but engaging and natural
                - Prioritize key learning points over lengthy explanations

                RESPONSE FORMAT:
                You must respond in JSON format with the following structure:
                {{
                    "response": "your conversational response here (18-20 words max)",
                    "learnWords": [
                        {{
                            "word": "학습할 단어나 표현",
                            "meaning": "{user_language}로 된 의미 설명",
                            "example": "예문 (선택사항)",
                            "pronunciation": "발음 (선택사항)"
                        }}
                    ]
                }}

                CRITICAL LEARNING WORDS REQUIREMENT:
                - You MUST include at least 1 learning word/expression in EVERY response
                - Include 1-3 useful words/expressions from your response in the learnWords array
                - If your response has no clear learning words, choose the most useful word anyway
                - Focus on words that are key to understanding or commonly used
                - Provide clear {user_language} meanings
                - Examples and pronunciation are optional but helpful
                - NEVER return an empty learnWords array

                Current difficulty: {difficulty_level}
                User's last message: "{last_user_message}"

                Respond naturally and keep the conversation flowing."""
            
            # 시스템 메시지 추가
            messages_for_api = [{"role": "system", "content": system_prompt}] + chat_history
            
            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=messages_for_api,
                max_tokens=150,
                temperature=0.7
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
                
                # 학습 단어가 비어있으면 기본 단어 추가
                if not learn_words and chat_response:
                    # 응답에서 첫 번째 의미있는 단어를 학습 단어로 추가
                    words = chat_response.split()
                    for word in words:
                        # 이모지나 특수문자 제외하고 알파벳 단어 찾기
                        clean_word = ''.join(c for c in word if c.isalpha())
                        if len(clean_word) > 2:  # 3글자 이상인 단어만
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
                # JSON 파싱 실패 시 텍스트 응답과 기본 학습 단어 반환
                if response_content:
                    words = response_content.split()
                    for word in words:
                        clean_word = ''.join(c for c in word if c.isalpha())
                        if len(clean_word) > 2:
                            default_word = LearnWord(
                                word=clean_word,
                                meaning=f"({user_language}로) 의미를 찾아보세요",
                                example=None,
                                pronunciation=None
                            )
                            return response_content, [default_word]
                
                return response_content, []
            
        except Exception as e:
            raise Exception(f"채팅 응답 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def text_to_speech(self, text: str, language: str, voice: Optional[str] = None) -> tuple[str, float]:
        """
        텍스트를 음성으로 변환하고 Cloudflare R2에 업로드합니다.
        """
        try:
            # 언어에 따른 음성 선택
            selected_voice = voice or self.voice_mapping.get(language, "alloy")
            
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=selected_voice,
                input=text
            )
            
            # 임시 파일로 저장
            import tempfile
            import time
            
            timestamp = int(time.time())
            filename = f"tts_{timestamp}.mp3"
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
            
            return audio_url, estimated_duration
            
        except Exception as e:
            raise Exception(f"음성 합성 중 오류가 발생했습니다: {str(e)}")
    
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