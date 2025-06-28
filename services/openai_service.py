import openai
import base64
import os
import random
from typing import Optional, List
from datetime import datetime
from config.settings import settings
from models.api_models import ChatMessage

class OpenAIService:
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        
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
    
    async def translate_text(self, text: str, from_language: str, to_language: str) -> str:
        """
        OpenAI를 사용하여 텍스트를 번역합니다.
        """
        try:
            # 번역 프롬프트 템플릿 (API 명세서 기준)
            prompt = f"""You are a professional translator.
Translate the given {from_language} text to natural {to_language}.
Only provide the {to_language} translation without any additional explanation or comments.

Text to translate: "{text}"
"""
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional translator. Provide accurate, natural translations without any additional explanations."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.3  # 번역의 일관성을 위해 낮은 temperature 사용
            )
            
            translated_text = response.choices[0].message.content.strip()
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
            
            prompt = f"""Generate a cheerful, encouraging first greeting for a language learning app.

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

Provide ONLY the welcome message without any additional explanation."""
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are MurMur, a cheerful AI language teacher. Generate welcome messages according to difficulty levels."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.7
            )
            
            welcome_message = response.choices[0].message.content.strip()
            
            # 폴백 메시지 생성 (영어)
            fallback_prompt = f"""Generate a simple English welcome message for a language learning app.
User name: {user_name}
Topic: {random_topic}

Keep it simple, friendly, and under 20 words. Include an emoji."""
            
            fallback_response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Generate simple, friendly English welcome messages."},
                    {"role": "user", "content": fallback_prompt}
                ],
                max_tokens=100,
                temperature=0.7
            )
            
            fallback_message = fallback_response.choices[0].message.content.strip()
            
            return welcome_message, fallback_message
            
        except Exception as e:
            raise Exception(f"환영 메시지 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def generate_chat_response(self, messages: List[ChatMessage], user_language: str, 
                                   ai_language: str, difficulty_level: str, last_user_message: str) -> str:
        """
        대화 응답을 생성합니다.
        """
        try:
            # 대화 히스토리를 OpenAI 형식으로 변환
            chat_history = []
            for msg in messages[-10:]:  # 최근 10개 메시지만 사용
                chat_history.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            # 대화 응답 생성 프롬프트
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

Current difficulty: {difficulty_level}
User's last message: "{last_user_message}"

Respond naturally and keep the conversation flowing."""
            
            # 시스템 메시지 추가
            messages_for_api = [{"role": "system", "content": system_prompt}] + chat_history
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages_for_api,
                max_tokens=200,
                temperature=0.8
            )
            
            chat_response = response.choices[0].message.content.strip()
            return chat_response
            
        except Exception as e:
            raise Exception(f"채팅 응답 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def text_to_speech(self, text: str, language: str, voice: Optional[str] = None) -> tuple[str, float]:
        """
        텍스트를 음성으로 변환합니다.
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
            
            # 실제 구현에서는 오디오 파일을 클라우드 스토리지에 업로드하고 URL 반환
            # 여기서는 로컬 파일 경로를 반환
            audio_url = f"/audio/{filename}"  # 실제로는 CDN URL이어야 함
            
            return audio_url, estimated_duration
            
        except Exception as e:
            raise Exception(f"음성 합성 중 오류가 발생했습니다: {str(e)}")
    
    async def test_api_key(self) -> bool:
        """
        API 키가 유효한지 테스트합니다.
        """
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            return True
        except Exception:
            return False

# 전역 OpenAI 서비스 인스턴스
openai_service = OpenAIService() 