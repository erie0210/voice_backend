import openai
import base64
import os
import random
import json
import time
import boto3
import logging
import hashlib
import tempfile
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydub import AudioSegment
from config.settings import settings
from models.api_models import ChatMessage, LearnWord, TopicEnum, ReactionCategory, EmotionCategory, ContinuationCategory
from services.r2_service import upload_file_to_r2, R2Service

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
        self.chat_responses_path = Path(__file__).parent.parent / "assets" / "chat_responses"
        
        # 음성 파일 메타데이터 캐시
        self._audio_metadata = None
        self._metadata_loaded = False
        
        # 반응 카테고리 캐시
        self._reaction_cache: Dict[str, List[str]] = {}
        
        # 감정 카테고리 캐시
        self._emotion_cache: Dict[str, List[str]] = {}
        
        # 이어가기 카테고리 캐시
        self._continuation_cache: Dict[str, List[str]] = {}
        
        # R2 서비스 인스턴스
        self.r2_service = R2Service()
    
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
    
    def _load_reaction_from_assets(self, reaction_category: ReactionCategory, user_language: str, ai_language: str) -> List[str]:
        """
        Assets 파일에서 특정 반응 카테고리의 텍스트를 로드합니다.
        """
        cache_key = f"{reaction_category.value}_{user_language}_{ai_language}"
        
        # 캐시된 반응이 있는지 확인
        if cache_key in self._reaction_cache:
            return self._reaction_cache[cache_key]
        
        try:
            # 반응 카테고리별 파일명 매핑
            reaction_files = {
                ReactionCategory.EMPATHY: "empathy.json",
                ReactionCategory.ACCEPTANCE: "acceptance.json",
                ReactionCategory.SURPRISE: "surprise.json",
                ReactionCategory.COMFORT: "comfort.json",
                ReactionCategory.JOY_SHARING: "joy_sharing.json",
                ReactionCategory.CONFIRMATION: "confirmation.json",
                ReactionCategory.SLOW_QUESTIONING: "slow_questioning.json"
            }
            
            filename = reaction_files.get(reaction_category, "empathy.json")
            reaction_file = self.chat_responses_path / "reactions" / filename
            
            if reaction_file.exists():
                with open(reaction_file, 'r', encoding='utf-8') as f:
                    reaction_data = json.load(f)
                    
                # from_{user_language} -> {ai_language} 경로로 찾기
                user_key = f"from_{user_language}"
                if user_key in reaction_data and ai_language in reaction_data[user_key]:
                    reactions = reaction_data[user_key][ai_language]
                    # 캐시에 저장
                    self._reaction_cache[cache_key] = reactions
                    return reactions
                else:
                    logger.warning(f"반응 조합을 찾을 수 없음: {user_language} -> {ai_language} for {reaction_category.value}")
                    return self._get_fallback_reaction(reaction_category)
            else:
                logger.warning(f"반응 파일을 찾을 수 없습니다: {reaction_file}")
                return self._get_fallback_reaction(reaction_category)
                
        except Exception as e:
            logger.error(f"반응 파일 로드 오류: {str(e)}")
            return self._get_fallback_reaction(reaction_category)
    
    def _get_fallback_reaction(self, reaction_category: ReactionCategory) -> List[str]:
        """
        폴백용 기본 반응
        """
        fallback_reactions = {
            ReactionCategory.EMPATHY: ["그랬구나~", "정말 그렇게 느꼈구나."],
            ReactionCategory.ACCEPTANCE: ["그래, 그런 기분 들 수 있어.", "누구나 그럴 수 있어."],
            ReactionCategory.SURPRISE: ["어, 진짜?", "정말 그런 일이 있었어?"],
            ReactionCategory.COMFORT: ["마음이 아팠겠다.", "속상했겠다~"],
            ReactionCategory.JOY_SHARING: ["우와~ 신났겠다!", "기분 좋았겠다!"],
            ReactionCategory.CONFIRMATION: ["그래서 그런 기분이었구나?", "그것 때문에 그랬구나?"],
            ReactionCategory.SLOW_QUESTIONING: ["다시 말해줄 수 있어?", "좀 더 알려줄래?"]
        }
        return fallback_reactions.get(reaction_category, ["그랬구나~"])
    
    def _analyze_user_message_for_reaction(self, user_message: str) -> ReactionCategory:
        """
        사용자 메시지를 분석해서 적절한 반응 카테고리를 선택합니다.
        """
        message_lower = user_message.lower()
        
        # 감정 키워드 기반 분석
        emotion_keywords = {
            # 기쁨, 행복 관련
            ReactionCategory.JOY_SHARING: [
                '기뻐', '좋아', '행복', '신나', '즐거', '재밌', '웃었', '웃긴', '최고', '대박',
                'happy', 'joy', 'good', 'great', 'awesome', 'amazing', 'wonderful', 'excited', 'fun', 'laugh'
            ],
            
            # 슬픔, 실망 관련  
            ReactionCategory.COMFORT: [
                '슬퍼', '속상', '화나', '짜증', '우울', '힘들', '아파', '상처', '울었', '눈물',
                'sad', 'hurt', 'angry', 'upset', 'disappointed', 'frustrated', 'depressed', 'cry', 'pain'
            ],
            
            # 놀람 관련
            ReactionCategory.SURPRISE: [
                '놀라', '갑자기', '진짜', '정말', '헐', '대박', '와', '어?', '그런데',
                'suddenly', 'really', 'wow', 'omg', 'amazing', 'incredible', 'unbelievable', 'shocking'
            ],
            
            # 확신이 없거나 불분명한 경우
            ReactionCategory.SLOW_QUESTIONING: [
                '잘 모르', '애매', '확실하지', '어떻게', '뭔가', '좀', '아직',
                "don't know", "not sure", "maybe", "kind of", "i think", "unclear", "confused"
            ]
        }
        
        # 키워드 매칭으로 카테고리 결정
        for category, keywords in emotion_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                logger.info(f"반응 카테고리 선택: {category.value} (키워드 매칭)")
                return category
        
        # 메시지 길이 기반 추가 판단
        if len(user_message.strip()) < 10:
            # 짧은 메시지는 천천히 되물음
            logger.info(f"반응 카테고리 선택: {ReactionCategory.SLOW_QUESTIONING.value} (짧은 메시지)")
            return ReactionCategory.SLOW_QUESTIONING
        
        # 기본적으로 공감 반응
        logger.info(f"반응 카테고리 선택: {ReactionCategory.EMPATHY.value} (기본값)")
        return ReactionCategory.EMPATHY
    
    def _load_emotion_from_assets(self, emotion_category: EmotionCategory, user_language: str, ai_language: str) -> List[str]:
        """
        Assets 파일에서 특정 감정 카테고리의 텍스트를 로드합니다.
        """
        cache_key = f"{emotion_category.value}_{user_language}_{ai_language}"
        
        # 캐시된 감정이 있는지 확인
        if cache_key in self._emotion_cache:
            return self._emotion_cache[cache_key]
        
        try:
            # 감정 카테고리별 파일명 매핑
            emotion_files = {
                EmotionCategory.HAPPY: "happy.json",
                EmotionCategory.SAD: "sad.json",
                EmotionCategory.ANGRY: "angry.json",
                EmotionCategory.SCARED: "scared.json",
                EmotionCategory.SHY: "shy.json",
                EmotionCategory.SLEEPY: "sleepy.json",
                EmotionCategory.UPSET: "upset.json",
                EmotionCategory.CONFUSED: "confused.json",
                EmotionCategory.BORED: "bored.json",
                EmotionCategory.LOVE: "love.json",
                EmotionCategory.PROUD: "proud.json",
                EmotionCategory.NERVOUS: "nervous.json"
            }
            
            filename = emotion_files.get(emotion_category, "happy.json")
            emotion_file = self.chat_responses_path / "emotions" / filename
            
            if emotion_file.exists():
                with open(emotion_file, 'r', encoding='utf-8') as f:
                    emotion_data = json.load(f)
                    
                # from_{user_language} -> {ai_language} 경로로 찾기
                user_key = f"from_{user_language}"
                if user_key in emotion_data and ai_language in emotion_data[user_key]:
                    emotions = emotion_data[user_key][ai_language]
                    # 캐시에 저장
                    self._emotion_cache[cache_key] = emotions
                    return emotions
                else:
                    logger.warning(f"감정 조합을 찾을 수 없음: {user_language} -> {ai_language} for {emotion_category.value}")
                    return self._get_fallback_emotion(emotion_category)
            else:
                logger.warning(f"감정 파일을 찾을 수 없습니다: {emotion_file}")
                return self._get_fallback_emotion(emotion_category)
                
        except Exception as e:
            logger.error(f"감정 파일 로드 오류: {str(e)}")
            return self._get_fallback_emotion(emotion_category)
    
    def _get_fallback_emotion(self, emotion_category: EmotionCategory) -> List[str]:
        """
        폴백용 기본 감정 설명
        """
        fallback_emotions = {
            EmotionCategory.HAPPY: ["Happy는 기쁠 때 쓰는 말이야.", "좋은 일이 생기면 happy~"],
            EmotionCategory.SAD: ["Sad는 마음이 아프거나 울고 싶을 때.", "슬플 때는 괜찮다고 말해줘도 돼."],
            EmotionCategory.ANGRY: ["Angry는 속상하고 짜증날 때 써.", "누군가 뺏으면 angry할 수 있어."],
            EmotionCategory.SCARED: ["Scared는 무서울 때, 깜짝 놀랐을 때 쓰는 말이야.", "어둠이 무서울 때 'I'm scared'라고 해."],
            EmotionCategory.SHY: ["Shy는 사람들이 많아서 말 못 할 때나, 얼굴이 빨개질 때.", "부끄러울 때 'I'm shy'라고 말해."],
            EmotionCategory.SLEEPY: ["Sleepy는 졸릴 때, 눈이 무거울 때 쓰는 말이야.", "잠이 올 때 'I'm sleepy'라고 해."],
            EmotionCategory.UPSET: ["Upset은 뭔가 기대했는데 안 됐을 때 마음이 울적할 때야.", "실망했을 때 'I'm upset'이라고 해."],
            EmotionCategory.CONFUSED: ["Confused는 잘 모르겠거나 헷갈릴 때 쓰는 말이야.", "복잡할 때 'I'm confused'라고 해."],
            EmotionCategory.BORED: ["Bored는 심심하고 할 게 없을 때 쓰는 말이야.", "재미없을 때 'I'm bored'라고 해."],
            EmotionCategory.LOVE: ["I love~는 너무너무 좋아할 때 쓰고, like는 그냥 좋아할 때!", "정말 좋아하는 걸 'I love it'이라고 해."],
            EmotionCategory.PROUD: ["Proud는 내가 잘했을 때 뿌듯한 기분이야.", "자랑스러울 때 'I'm proud'라고 해."],
            EmotionCategory.NERVOUS: ["Nervous는 발표 전처럼 두근거릴 때 쓰는 말이야.", "긴장될 때 'I'm nervous'라고 해."]
        }
        return fallback_emotions.get(emotion_category, ["그런 기분을 영어로 표현해보자."])
    
    def _analyze_user_message_for_emotion(self, user_message: str, reaction_category: ReactionCategory) -> EmotionCategory:
        """
        사용자 메시지와 반응 카테고리를 기반으로 적절한 감정 카테고리를 선택합니다.
        """
        message_lower = user_message.lower()
        
        # 반응 카테고리에 따른 감정 매핑
        reaction_to_emotion = {
            ReactionCategory.JOY_SHARING: [EmotionCategory.HAPPY, EmotionCategory.LOVE, EmotionCategory.PROUD],
            ReactionCategory.COMFORT: [EmotionCategory.SAD, EmotionCategory.UPSET, EmotionCategory.SCARED],
            ReactionCategory.SURPRISE: [EmotionCategory.CONFUSED, EmotionCategory.NERVOUS],
            ReactionCategory.EMPATHY: [EmotionCategory.HAPPY, EmotionCategory.SAD],
            ReactionCategory.ACCEPTANCE: [EmotionCategory.ANGRY, EmotionCategory.UPSET],
            ReactionCategory.CONFIRMATION: [EmotionCategory.CONFUSED, EmotionCategory.UPSET],
            ReactionCategory.SLOW_QUESTIONING: [EmotionCategory.SHY, EmotionCategory.CONFUSED]
        }
        
        # 키워드 기반 감정 분석
        emotion_keywords = {
            EmotionCategory.HAPPY: ['기뻐', '좋아', '행복', '신나', '즐거', '재밌', '웃었', '최고', 'happy', 'joy', 'good', 'great', 'fun', 'love'],
            EmotionCategory.SAD: ['슬퍼', '속상', '울었', '눈물', '외로', 'sad', 'cry', 'tear', 'lonely'],
            EmotionCategory.ANGRY: ['화나', '짜증', '빡쳐', '열받', '약올라', 'angry', 'mad', 'frustrated', 'annoyed'],
            EmotionCategory.SCARED: ['무서', '놀라', '깜짝', '겁나', '두려', 'scared', 'afraid', 'frightened', 'terrified'],
            EmotionCategory.SHY: ['부끄러', '창피', '민망', '수줍', 'shy', 'embarrassed', 'awkward'],
            EmotionCategory.SLEEPY: ['졸려', '피곤', '잠와', '꾸벅', '눈감', 'sleepy', 'tired', 'drowsy'],
            EmotionCategory.UPSET: ['실망', '허탈', '기대했는데', '안됐', 'upset', 'disappointed', 'frustrated'],
            EmotionCategory.CONFUSED: ['헷갈려', '모르겠', '복잡', '어려', '이해못', 'confused', 'puzzled', 'unclear'],
            EmotionCategory.BORED: ['심심', '지겨', '재미없', '할거없', 'bored', 'boring', 'dull'],
            EmotionCategory.LOVE: ['사랑', '정말좋아', '너무좋아', '최애', 'love', 'adore', 'favorite'],
            EmotionCategory.PROUD: ['자랑스러', '뿌듯', '잘했', '성공', '대견', 'proud', 'accomplished', 'achieved'],
            EmotionCategory.NERVOUS: ['긴장', '떨려', '두근', '불안', '걱정', 'nervous', 'anxious', 'worried']
        }
        
        # 키워드 매칭으로 감정 결정
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                logger.info(f"감정 카테고리 선택: {emotion.value} (키워드 매칭)")
                return emotion
        
        # 키워드 매칭 실패 시 반응 카테고리 기반 선택
        possible_emotions = reaction_to_emotion.get(reaction_category, [EmotionCategory.HAPPY])
        selected_emotion = random.choice(possible_emotions)
        
        logger.info(f"감정 카테고리 선택: {selected_emotion.value} (반응 기반 매핑)")
        return selected_emotion
    
    def _load_continuation_from_assets(self, continuation_category: ContinuationCategory, user_language: str, ai_language: str) -> List[str]:
        """
        Assets 파일에서 특정 이어가기 카테고리의 텍스트를 로드합니다.
        """
        cache_key = f"{continuation_category.value}_{user_language}_{ai_language}"
        
        # 캐시된 이어가기가 있는지 확인
        if cache_key in self._continuation_cache:
            return self._continuation_cache[cache_key]
        
        try:
            # 이어가기 카테고리별 파일명 매핑
            continuation_files = {
                ContinuationCategory.EMOTION_EXPLORATION: "emotion_exploration.json",
                ContinuationCategory.EMOTION_ACTION: "emotion_action.json",
                ContinuationCategory.EMOTION_LEARNING: "emotion_learning.json",
                ContinuationCategory.QUESTION_EXPANSION: "question_expansion.json",
                ContinuationCategory.ENCOURAGEMENT_FLOW: "encouragement_flow.json",
                ContinuationCategory.EMOTION_TRANSITION: "emotion_transition.json"
            }
            
            filename = continuation_files.get(continuation_category, "emotion_exploration.json")
            continuation_file = self.chat_responses_path / "continuations" / filename
            
            if continuation_file.exists():
                with open(continuation_file, 'r', encoding='utf-8') as f:
                    continuation_data = json.load(f)
                    
                # from_{user_language} -> {ai_language} 경로로 찾기
                user_key = f"from_{user_language}"
                if user_key in continuation_data and ai_language in continuation_data[user_key]:
                    continuations = continuation_data[user_key][ai_language]
                    # 캐시에 저장
                    self._continuation_cache[cache_key] = continuations
                    return continuations
                else:
                    logger.warning(f"이어가기 조합을 찾을 수 없음: {user_language} -> {ai_language} for {continuation_category.value}")
                    return self._get_fallback_continuation(continuation_category)
            else:
                logger.warning(f"이어가기 파일을 찾을 수 없습니다: {continuation_file}")
                return self._get_fallback_continuation(continuation_category)
                
        except Exception as e:
            logger.error(f"이어가기 파일 로드 오류: {str(e)}")
            return self._get_fallback_continuation(continuation_category)
    
    def _get_fallback_continuation(self, continuation_category: ContinuationCategory) -> List[str]:
        """
        폴백용 기본 이어가기 질문
        """
        fallback_continuations = {
            ContinuationCategory.EMOTION_EXPLORATION: ["왜 그렇게 느꼈는지 말해줄 수 있어?", "그럴 땐 어떤 생각이 들었어?"],
            ContinuationCategory.EMOTION_ACTION: ["그럴 땐 뭘 하고 싶어졌어?", "그런 기분일 때 뭘 하면 도움이 될까?"],
            ContinuationCategory.EMOTION_LEARNING: ["영어로도 말해볼래?", "이 기분을 영어로 표현해볼까?"],
            ContinuationCategory.QUESTION_EXPANSION: ["다른 사람은 어떻게 느꼈을까?", "이전에 이런 기분 느낀 적 있어?"],
            ContinuationCategory.ENCOURAGEMENT_FLOW: ["말해줘서 고마워~", "네 마음을 표현하는 게 정말 잘했어."],
            ContinuationCategory.EMOTION_TRANSITION: ["우리 깊게 숨 쉬어볼까?", "좋아하는 노래 하나 불러볼까?"]
        }
        return fallback_continuations.get(continuation_category, ["더 얘기해볼까?"])
    
    def _analyze_for_continuation_category(self, emotion_category: EmotionCategory, reaction_category: ReactionCategory, user_message: str) -> ContinuationCategory:
        """
        감정 카테고리, 반응 카테고리, 사용자 메시지를 기반으로 적절한 이어가기 카테고리를 선택합니다.
        """
        message_lower = user_message.lower()
        
        # 메시지 길이 기반 판단
        if len(user_message.strip()) < 10:
            # 짧은 메시지는 감정 탐색으로 더 깊이 물어보기
            logger.info(f"이어가기 카테고리 선택: {ContinuationCategory.EMOTION_EXPLORATION.value} (짧은 메시지)")
            return ContinuationCategory.EMOTION_EXPLORATION
        
        # 영어 학습 관련 키워드 감지
        learning_keywords = ['영어', '말해', '표현', 'english', 'say', 'how', 'what']
        if any(keyword in message_lower for keyword in learning_keywords):
            logger.info(f"이어가기 카테고리 선택: {ContinuationCategory.EMOTION_LEARNING.value} (학습 키워드)")
            return ContinuationCategory.EMOTION_LEARNING
        
        # 감정 카테고리에 따른 이어가기 전략
        emotion_to_continuation = {
            # 긍정적 감정은 질문 확장이나 격려
            EmotionCategory.HAPPY: [ContinuationCategory.QUESTION_EXPANSION, ContinuationCategory.ENCOURAGEMENT_FLOW],
            EmotionCategory.LOVE: [ContinuationCategory.QUESTION_EXPANSION, ContinuationCategory.ENCOURAGEMENT_FLOW],
            EmotionCategory.PROUD: [ContinuationCategory.QUESTION_EXPANSION, ContinuationCategory.ENCOURAGEMENT_FLOW],
            
            # 부정적 감정은 감정 탐색이나 전환 유도
            EmotionCategory.SAD: [ContinuationCategory.EMOTION_EXPLORATION, ContinuationCategory.EMOTION_TRANSITION],
            EmotionCategory.ANGRY: [ContinuationCategory.EMOTION_ACTION, ContinuationCategory.EMOTION_TRANSITION],
            EmotionCategory.SCARED: [ContinuationCategory.EMOTION_EXPLORATION, ContinuationCategory.EMOTION_TRANSITION],
            EmotionCategory.UPSET: [ContinuationCategory.EMOTION_EXPLORATION, ContinuationCategory.EMOTION_ACTION],
            
            # 중성적 감정은 상황에 따라
            EmotionCategory.SHY: [ContinuationCategory.EMOTION_EXPLORATION, ContinuationCategory.ENCOURAGEMENT_FLOW],
            EmotionCategory.NERVOUS: [ContinuationCategory.EMOTION_ACTION, ContinuationCategory.EMOTION_TRANSITION],
            EmotionCategory.CONFUSED: [ContinuationCategory.EMOTION_EXPLORATION, ContinuationCategory.EMOTION_ACTION],
            EmotionCategory.BORED: [ContinuationCategory.QUESTION_EXPANSION, ContinuationCategory.EMOTION_TRANSITION],
            EmotionCategory.SLEEPY: [ContinuationCategory.EMOTION_ACTION, ContinuationCategory.EMOTION_TRANSITION]
        }
        
        # 반응 카테고리에 따른 추가 조정
        if reaction_category in [ReactionCategory.COMFORT, ReactionCategory.ACCEPTANCE]:
            # 위로나 수용 반응 후에는 감정 전환 유도
            logger.info(f"이어가기 카테고리 선택: {ContinuationCategory.EMOTION_TRANSITION.value} (위로/수용 후 전환)")
            return ContinuationCategory.EMOTION_TRANSITION
        elif reaction_category == ReactionCategory.SLOW_QUESTIONING:
            # 천천히 되물음 후에는 감정 탐색
            logger.info(f"이어가기 카테고리 선택: {ContinuationCategory.EMOTION_EXPLORATION.value} (더 깊은 탐색)")
            return ContinuationCategory.EMOTION_EXPLORATION
        
        # 감정 기반 선택
        possible_continuations = emotion_to_continuation.get(emotion_category, [ContinuationCategory.QUESTION_EXPANSION])
        selected_continuation = random.choice(possible_continuations)
        
        logger.info(f"이어가기 카테고리 선택: {selected_continuation.value} (감정 기반 매핑)")
        return selected_continuation
    
    async def _analyze_user_message_with_openai(self, user_message: str, user_language: str) -> tuple[ReactionCategory, EmotionCategory, ContinuationCategory]:
        """
        OpenAI를 사용하여 사용자 메시지를 분석하고 최적의 3단계 카테고리 조합을 선택합니다.
        
        Args:
            user_message: 사용자 메시지
            user_language: 사용자 언어
            
        Returns:
            tuple: (reaction_category, emotion_category, continuation_category)
        """
        try:
            # 카테고리 설명을 포함한 시스템 프롬프트
            system_content = f"""당신은 언어 학습 AI 튜터입니다. 사용자의 메시지를 분석하여 가장 적절한 3단계 응답 조합을 선택해주세요.

**1단계: 반응 카테고리 (REACTION)**
- EMPATHY: 🙋‍♀️ 공감 - "그랬구나~", "정말 그렇게 느꼈구나."
- ACCEPTANCE: 🫶 수용 - "그래, 그런 기분 들 수 있어."
- SURPRISE: 😮 놀람 - "어, 진짜?", "정말 그런 일이 있었어?"
- COMFORT: 😢 위로 - "마음이 아팠겠다.", "정말 속상했겠다."
- JOY_SHARING: 😊 기쁨 나눔 - "우와~ 신났겠다!", "기분 좋았겠다!"
- CONFIRMATION: 🤔 확인/공명 - "~해서 슬펐던 거야?", "화가 나서 그런 기분이 들었구나?"
- SLOW_QUESTIONING: 🐢 천천히 되물음 - "다시 말해줄 수 있어?", "좀 더 알려줄래?"

**2단계: 감정 카테고리 (EMOTION)**
- HAPPY: 😄 기쁨 - "Happy는 기쁠 때 쓰는 말이야."
- SAD: 😢 슬픔 - "Sad는 마음이 아프거나 울고 싶을 때."
- ANGRY: 😠 화남 - "Angry는 속상하고 짜증날 때 써."
- SCARED: 😨 무서움 - "Scared는 무서울 때, 깜짝 놀랐을 때 쓰는 말이야."
- SHY: 😳 부끄러움 - "Shy는 사람들이 많아서 말 못 할 때나, 얼굴이 빨개질 때."
- SLEEPY: 😴 졸림 - "Sleepy는 졸릴 때, 눈이 무거울 때 쓰는 말이야."
- UPSET: 😔 속상함 - "Upset은 뭔가 기대했는데 안 됐을 때 마음이 울적할 때야."
- CONFUSED: 😵 혼란/당황 - "Confused는 잘 모르겠거나 헷갈릴 때 쓰는 말이야."
- BORED: 🥱 지루함 - "Bored는 심심하고 할 게 없을 때 쓰는 말이야."
- LOVE: 😍 좋아함 - "I love~는 너무너무 좋아할 때 쓰고, like는 그냥 좋아할 때!"
- PROUD: 😎 자랑스러움 - "Proud는 내가 잘했을 때 뿌듯한 기분이야."
- NERVOUS: 😬 긴장됨 - "Nervous는 발표 전처럼 두근거릴 때 쓰는 말이야."

**3단계: 이어가기 카테고리 (CONTINUATION)**
- EMOTION_EXPLORATION: 감정 탐색 - "왜 그렇게 느꼈는지 말해줄 수 있어?"
- EMOTION_ACTION: 🧩 감정+행동 연결 - "그럴 땐 뭘 하고 싶어졌어?"
- EMOTION_LEARNING: 📚 감정+표현 학습 - "그건 angry라고 해. 한 번 말해볼까?"
- QUESTION_EXPANSION: 💬 질문 확장 - "너는 언제 제일 happy해?"
- ENCOURAGEMENT_FLOW: 🌟 격려 + 다음 흐름 - "말해줘서 고마워~"
- EMOTION_TRANSITION: 🌈 감정 전환 유도 - "우리 깊게 숨 쉬어볼까?"

사용자 메시지의 감정, 상황, 맥락을 고려하여 가장 적절한 조합을 선택해주세요.

JSON 형식으로만 응답하세요:
{{
  "reaction": "카테고리명",
  "emotion": "카테고리명", 
  "continuation": "카테고리명",
  "reasoning": "선택 이유 (간단히)"
}}"""

            user_prompt = f"""사용자 메시지 ({user_language}): "{user_message}"

이 메시지에 가장 적절한 3단계 응답 조합을 선택해주세요."""

            response = self.client.chat.completions.create(
                model=self.default_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=200,
                temperature=0.3,  # 일관성 있는 선택을 위해 낮은 온도
                response_format={"type": "json_object"}
            )
            
            response_content = response.choices[0].message.content.strip()
            
            try:
                parsed_response = json.loads(response_content)
                
                # 카테고리 변환
                reaction_str = parsed_response.get("reaction", "EMPATHY")
                emotion_str = parsed_response.get("emotion", "HAPPY")
                continuation_str = parsed_response.get("continuation", "QUESTION_EXPANSION")
                reasoning = parsed_response.get("reasoning", "")
                
                # Enum으로 변환
                try:
                    reaction_category = ReactionCategory(reaction_str)
                except ValueError:
                    logger.warning(f"유효하지 않은 반응 카테고리: {reaction_str}, 기본값 사용")
                    reaction_category = ReactionCategory.EMPATHY
                
                try:
                    emotion_category = EmotionCategory(emotion_str)
                except ValueError:
                    logger.warning(f"유효하지 않은 감정 카테고리: {emotion_str}, 기본값 사용")
                    emotion_category = EmotionCategory.HAPPY
                
                try:
                    continuation_category = ContinuationCategory(continuation_str)
                except ValueError:
                    logger.warning(f"유효하지 않은 이어가기 카테고리: {continuation_str}, 기본값 사용")
                    continuation_category = ContinuationCategory.QUESTION_EXPANSION
                
                logger.info(f"OpenAI 카테고리 선택 완료:")
                logger.info(f"  - 반응: {reaction_category.value}")
                logger.info(f"  - 감정: {emotion_category.value}")
                logger.info(f"  - 이어가기: {continuation_category.value}")
                logger.info(f"  - 선택 이유: {reasoning}")
                
                return reaction_category, emotion_category, continuation_category
                
            except json.JSONDecodeError as e:
                logger.error(f"OpenAI 응답 JSON 파싱 실패: {str(e)}")
                logger.error(f"응답 내용: {response_content}")
                # 폴백: 기본 규칙 기반 선택
                return self._fallback_category_selection(user_message)
                
        except Exception as e:
            logger.error(f"OpenAI 카테고리 분석 오류: {str(e)}")
            # 폴백: 기본 규칙 기반 선택
            return self._fallback_category_selection(user_message)
    
    def _fallback_category_selection(self, user_message: str) -> tuple[ReactionCategory, EmotionCategory, ContinuationCategory]:
        """
        OpenAI 분석 실패시 사용할 폴백 카테고리 선택
        """
        logger.info("폴백 카테고리 선택 사용")
        
        # 기존 규칙 기반 방식 사용
        reaction_category = self._analyze_user_message_for_reaction(user_message)
        emotion_category = self._analyze_user_message_for_emotion(user_message, reaction_category)
        continuation_category = self._analyze_for_continuation_category(emotion_category, reaction_category, user_message)
        
        return reaction_category, emotion_category, continuation_category
    
    async def generate_templated_chat_response(self, messages: List[ChatMessage], user_language: str, 
                                             ai_language: str, difficulty_level: str, last_user_message: str) -> tuple[str, List[LearnWord], Optional[str]]:
        """
        템플릿 기반으로 채팅 응답을 생성합니다.
        1) 반응 및 수용 2) 설명 및 확장 3) 따라말하기 구조로 구성됩니다.
        
        Returns:
            tuple: (response, learn_words, audio_url)
        """
        try:
            # OpenAI를 사용하여 사용자 메시지 분석 및 최적의 3단계 카테고리 조합 선택
            logger.info(f"사용자 메시지 OpenAI 분석 시작: {last_user_message}")
            reaction_category, emotion_category, continuation_category = await self._analyze_user_message_with_openai(last_user_message, user_language)
            
            # 1) 반응 및 수용 - 선택된 카테고리로 템플릿 로드
            reactions = self._load_reaction_from_assets(reaction_category, user_language, ai_language)
            selected_reaction = random.choice(reactions)
            
            logger.info(f"선택된 반응: {selected_reaction} (카테고리: {reaction_category.value})")
            
            # 2) 설명 및 확장 - 선택된 카테고리로 템플릿 로드
            emotions = self._load_emotion_from_assets(emotion_category, user_language, ai_language)
            selected_expansion = random.choice(emotions)
            
            logger.info(f"선택된 감정 설명: {selected_expansion} (카테고리: {emotion_category.value})")
            
            # 3) 이야기 이어가기 - 선택된 카테고리로 템플릿 로드
            continuations = self._load_continuation_from_assets(continuation_category, user_language, ai_language)
            selected_continuation = random.choice(continuations)
            
            logger.info(f"선택된 이어가기: {selected_continuation} (카테고리: {continuation_category.value})")
            
            # 전체 응답 조합
            full_response = f"{selected_reaction} {selected_expansion} {selected_continuation}"
            
            # 학습 단어 생성 - 감정 카테고리 기반
            emotion_word_mapping = {
                EmotionCategory.HAPPY: ("happy", "기쁜, 행복한", "I'm happy today!", "해피"),
                EmotionCategory.SAD: ("sad", "슬픈, 속상한", "I feel sad.", "새드"),
                EmotionCategory.ANGRY: ("angry", "화난, 짜증난", "I'm angry about this.", "앵그리"),
                EmotionCategory.SCARED: ("scared", "무서운, 두려운", "I'm scared of the dark.", "스케어드"),
                EmotionCategory.SHY: ("shy", "부끄러운, 수줍은", "I'm shy around new people.", "샤이"),
                EmotionCategory.SLEEPY: ("sleepy", "졸린, 피곤한", "I'm sleepy now.", "슬리피"),
                EmotionCategory.UPSET: ("upset", "속상한, 실망한", "I'm upset about the news.", "업셋"),
                EmotionCategory.CONFUSED: ("confused", "혼란스러운, 헷갈린", "I'm confused about this.", "컨퓨즈드"),
                EmotionCategory.BORED: ("bored", "지루한, 심심한", "I'm bored at home.", "보어드"),
                EmotionCategory.LOVE: ("love", "사랑, 매우 좋아함", "I love this song!", "러브"),
                EmotionCategory.PROUD: ("proud", "자랑스러운, 뿌듯한", "I'm proud of you.", "프라우드"),
                EmotionCategory.NERVOUS: ("nervous", "긴장한, 불안한", "I'm nervous about the test.", "너버스")
            }
            
            emotion_word_data = emotion_word_mapping.get(emotion_category, ("happy", "기쁜", "I'm happy!", "해피"))
            
            learn_words = [
                LearnWord(
                    word=emotion_word_data[0],
                    meaning=emotion_word_data[1],
                    example=emotion_word_data[2],
                    pronunciation=emotion_word_data[3]
                ),
                LearnWord(
                    word="feeling",
                    meaning="기분, 감정",
                    example="How are you feeling?",
                    pronunciation="필링"
                )
            ]
            
            # 3단계 모든 음성 URL 찾기 및 합치기
            audio_url = None
            try:
                # 3단계 모든 음성 URL 찾기
                reaction_audio_url, emotion_audio_url, continuation_audio_url = self._find_all_audio_urls_for_templated_response(
                    selected_reaction, reaction_category,
                    selected_expansion, emotion_category,
                    selected_continuation, continuation_category,
                    user_language, ai_language
                )
                
                # 찾은 음성 URL들을 합치기
                valid_audio_urls = []
                if reaction_audio_url:
                    valid_audio_urls.append(reaction_audio_url)
                    logger.info(f"반응 음성 파일 URL 찾음: {reaction_audio_url}")
                if emotion_audio_url:
                    valid_audio_urls.append(emotion_audio_url)
                    logger.info(f"감정 설명 음성 파일 URL 찾음: {emotion_audio_url}")
                if continuation_audio_url:
                    valid_audio_urls.append(continuation_audio_url)
                    logger.info(f"이어가기 음성 파일 URL 찾음: {continuation_audio_url}")
                
                if valid_audio_urls:
                    logger.info(f"총 {len(valid_audio_urls)}개 음성 파일을 합치는 중...")
                    audio_url = await self._combine_audio_files(valid_audio_urls)
                    
                    if audio_url:
                        logger.info(f"합쳐진 음성 파일 URL: {audio_url}")
                    else:
                        logger.warning("음성 파일 합치기 실패, 폴백 음성 사용")
                        # 폴백: 첫 번째 유효한 음성 사용
                        audio_url = valid_audio_urls[0] if valid_audio_urls else None
                else:
                    logger.info(f"음성 파일을 찾을 수 없음: {reaction_category.value}, {emotion_category.value}, {continuation_category.value}")
                    
            except Exception as e:
                logger.error(f"음성 파일 처리 오류: {str(e)}")
            
            return full_response, learn_words, audio_url
            
        except Exception as e:
            logger.error(f"템플릿 기반 채팅 응답 생성 오류: {str(e)}")
            # 폴백: 기본 응답 사용
            fallback_response = "그렇구나~ 더 말해줄래?"
            fallback_words = [
                LearnWord(word="more", meaning="더", example="Tell me more.", pronunciation="모어")
            ]
            return fallback_response, fallback_words, None
    
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
            elif category.startswith("reactions/"):
                # reactions의 경우 (e.g., "reactions/empathy" -> "empathy")
                reaction_name = category.split("/")[-1] if "/" in category else category
                metadata_section = self._audio_metadata.get("reactions", {}).get(reaction_name, {})
            elif category.startswith("emotions/"):
                # emotions의 경우 (e.g., "emotions/happy" -> "happy")
                emotion_name = category.split("/")[-1] if "/" in category else category
                metadata_section = self._audio_metadata.get("emotions", {}).get(emotion_name, {})
            elif category.startswith("continuations/"):
                # continuations의 경우 (e.g., "continuations/emotion_exploration" -> "emotion_exploration")
                continuation_name = category.split("/")[-1] if "/" in category else category
                metadata_section = self._audio_metadata.get("continuations", {}).get(continuation_name, {})
            else:
                # topics의 경우 (e.g., "topics/favorites" -> "favorites")
                topic_name = category.split("/")[-1] if "/" in category else category
                metadata_section = self._audio_metadata.get("topics", {}).get(topic_name, {})
            
            # from_lang -> 응답언어(사용자 언어) 경로로 찾기
            user_key = f"from_{from_lang}"
            if user_key not in metadata_section:
                return None
                
            # AI 응답은 사용자 언어로 나가야 함
            lang_section = metadata_section[user_key].get(from_lang, [])
            
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
    
    def _find_all_audio_urls_for_templated_response(self, 
                                                   selected_reaction: str, reaction_category: ReactionCategory,
                                                   selected_expansion: str, emotion_category: EmotionCategory,
                                                   selected_continuation: str, continuation_category: ContinuationCategory,
                                                   user_language: str, ai_language: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        3단계 템플릿 응답에 대응하는 모든 음성 URL을 찾습니다.
        
        Returns:
            tuple: (reaction_audio_url, emotion_audio_url, continuation_audio_url)
        """
        try:
            # 1) 반응 음성 URL 찾기
            reaction_audio_url = self._find_audio_url_for_text(
                selected_reaction,
                "reactions/" + reaction_category.value.lower(),
                user_language,
                ai_language
            )
            
            # 2) 감정 설명 음성 URL 찾기
            emotion_audio_url = self._find_audio_url_for_text(
                selected_expansion,
                "emotions/" + emotion_category.value.lower(),
                user_language,
                ai_language
            )
            
            # 3) 이어가기 음성 URL 찾기
            continuation_audio_url = self._find_audio_url_for_text(
                selected_continuation,
                "continuations/" + continuation_category.value.lower(),
                user_language,
                ai_language
            )
            
            logger.info(f"음성 URL 검색 결과: 반응={bool(reaction_audio_url)}, 감정={bool(emotion_audio_url)}, 이어가기={bool(continuation_audio_url)}")
            
            return reaction_audio_url, emotion_audio_url, continuation_audio_url
            
        except Exception as e:
            logger.error(f"모든 음성 URL 찾기 오류: {str(e)}")
            return None, None, None
    
    async def _download_audio_file(self, url: str) -> Optional[bytes]:
        """
        음성 파일을 다운로드합니다.
        
        Args:
            url: 다운로드할 음성 파일 URL
            
        Returns:
            bytes: 다운로드된 음성 파일 데이터 (실패시 None)
        """
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"음성 파일 다운로드 실패 ({url}): {str(e)}")
            return None
    
    async def _combine_audio_files(self, audio_urls: List[str]) -> Optional[str]:
        """
        여러 음성 파일을 하나로 합칩니다.
        
        Args:
            audio_urls: 합칠 음성 파일 URL 리스트
            
        Returns:
            str: 합쳐진 음성 파일의 R2 URL (실패시 None)
        """
        try:
            # 빈 URL 제거
            valid_urls = [url for url in audio_urls if url]
            if not valid_urls:
                logger.warning("합칠 유효한 음성 URL이 없습니다.")
                return None
            
            if len(valid_urls) == 1:
                # 하나의 URL만 있으면 그대로 반환
                logger.info("음성 파일이 하나뿐이므로 합치기 건너뜀")
                return valid_urls[0]
            
            # 임시 파일들을 저장할 리스트
            audio_segments = []
            temp_files = []
            
            # 각 음성 파일 다운로드 및 로드
            for i, url in enumerate(valid_urls):
                logger.info(f"음성 파일 {i+1}/{len(valid_urls)} 다운로드 중: {url}")
                
                audio_data = await self._download_audio_file(url)
                if not audio_data:
                    logger.warning(f"음성 파일 다운로드 실패, 건너뜀: {url}")
                    continue
                
                # 임시 파일에 저장
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                    temp_file.write(audio_data)
                    temp_file_path = temp_file.name
                    temp_files.append(temp_file_path)
                
                # AudioSegment로 로드
                try:
                    audio_segment = AudioSegment.from_mp3(temp_file_path)
                    audio_segments.append(audio_segment)
                    logger.info(f"음성 파일 로드 성공: {len(audio_segment)}ms")
                except Exception as e:
                    logger.error(f"음성 파일 로드 실패: {str(e)}")
                    continue
            
            if not audio_segments:
                logger.error("로드된 음성 세그먼트가 없습니다.")
                return None
            
            # 음성 파일들을 연결 (사이에 0.5초 간격 추가)
            logger.info(f"{len(audio_segments)}개 음성 파일 합치는 중...")
            silence = AudioSegment.silent(duration=500)  # 0.5초 무음
            
            combined_audio = audio_segments[0]
            for segment in audio_segments[1:]:
                combined_audio = combined_audio + silence + segment
            
            # 합쳐진 음성을 임시 파일로 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as combined_temp:
                combined_audio.export(combined_temp.name, format="mp3", bitrate="128k")
                combined_temp_path = combined_temp.name
            
            # 합쳐진 파일을 R2에 업로드
            with open(combined_temp_path, 'rb') as f:
                combined_audio_data = f.read()
            
            # 고유한 파일명 생성 (현재 시간 + 해시)
            timestamp = int(time.time())
            audio_hash = hashlib.md5(combined_audio_data).hexdigest()[:8]
            combined_file_path = f"conversation_starters/combined_audio/{timestamp}_{audio_hash}.mp3"
            
            # R2에 업로드
            upload_success = await self.r2_service.upload_file(
                file_content=combined_audio_data,
                file_path=combined_file_path,
                content_type="audio/mpeg"
            )
            
            if upload_success:
                combined_url = f"https://voice.kreators.dev/{combined_file_path}"
                logger.info(f"합쳐진 음성 파일 업로드 성공: {combined_url}")
                
                # 임시 파일들 정리
                for temp_file in temp_files + [combined_temp_path]:
                    try:
                        os.unlink(temp_file)
                    except Exception as e:
                        logger.warning(f"임시 파일 삭제 실패: {str(e)}")
                
                return combined_url
            else:
                logger.error("합쳐진 음성 파일 업로드 실패")
                return None
                
        except Exception as e:
            logger.error(f"음성 파일 합치기 오류: {str(e)}")
            return None
        finally:
            # 임시 파일들 정리 (에러 발생시에도)
            try:
                for temp_file in temp_files:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                if 'combined_temp_path' in locals() and os.path.exists(combined_temp_path):
                    os.unlink(combined_temp_path)
            except Exception as e:
                logger.warning(f"임시 파일 정리 오류: {str(e)}")
    
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
You are a language teacher helping users learn {ai_language}. You primarily use {user_language} and introduce {ai_language} expressions.

ROLE: Language teacher who speaks {user_language} and helps students learn {ai_language}
- Be encouraging and supportive like talking to a beginner
- Use {user_language} as primary language for explanations
- Introduce simple {ai_language} expressions with Korean explanations
- Give pronunciation tips in Korean

RESPONSE FLOW (naturally blend these steps):
- Start with a brief reaction to user's message ({user_language})
- Naturally paraphrase what they said in one sentence ({user_language})
- Introduce related {ai_language} expression with explanation and pronunciation
- Continue with a related question to keep the conversation going

Example: "그랬구나~ 정말 기분이 좋았겠다! 너가 '오늘 정말 행복했어'라고 말했는데, 이걸 영어로는 'I'm so happy today!'라고 해. 발음은 '아임 소 해피 투데이'야. 그런데 뭐가 그렇게 행복하게 만들었어?"
""",
                "intermediate": f"""
You are a language teacher helping users learn {ai_language}. Reply primarily in {ai_language} with simple vocabulary.

ROLE: Kind elementary school teacher who teaches {ai_language}
- Use elementary level {ai_language} vocabulary
- Provide gentle corrections and natural expressions
- Focus on practical, everyday expressions

RESPONSE FLOW (naturally blend these steps):
- Start with a brief reaction to user's message
- Naturally paraphrase their expression in natural {ai_language}
- Introduce related {ai_language} expression with explanation
- Continue with a related question to keep talking

Example: "That's great! You said you were happy, which sounds natural. We can also say 'I'm thrilled!' - it means very excited and happy. What made you feel so happy today?"
""",
                "advanced": f"""
You are a language teacher helping users learn {ai_language}. Reply only in {ai_language} with sophisticated expressions.

ROLE: Native {ai_language} speaker at middle school level
- Use natural, sophisticated {ai_language} expressions
- Challenge users with advanced vocabulary and concepts
- Engage in deeper discussions on various topics

RESPONSE FLOW (naturally blend these steps):
- Start with a natural reaction to user's message
- Naturally paraphrase their expression in sophisticated {ai_language}
- Introduce advanced {ai_language} expression/idiom with explanation
- Continue with thought-provoking questions

Example: "Absolutely! You mentioned feeling happy, which we could also express as 'I'm over the moon!' - it's an idiom meaning extremely happy. What aspects of your experience contributed most to this feeling of joy?"
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
            system_prompt = f"""You are MurMur, a language teacher helping students learn {ai_language}.

SPECIAL: If user says "Hello, Start to Talk!": Brief intro + topic question.

TEACHING APPROACH:
- You are a teacher who uses {user_language} and helps students learn {ai_language}
- Follow the natural flow: React to user → Paraphrase their expression → Introduce new expression → Continue conversation

CURRENT LEVEL ({difficulty_level.upper()}):
{current_level_prompt}

LEARN WORDS: Always provide 2-3 {ai_language} expressions. The main expression taught must appear in learnWords.

RESPONSE LENGTH: {current_word_limit}{final_message_instruction}

Return valid JSON:
{{
  "response": "your natural response following the teaching flow",
  "learnWords": [{{"word":"expression","meaning":"explanation","example":"usage","pronunciation":"phonetic"}}]
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
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            return True
        except Exception as e:
            logger.error(f"API 키 테스트 실패: {str(e)}")
            return False
    
    async def get_chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 1000, response_format: Optional[Dict[str, Any]] = None) -> Any:
        """
        OpenAI Chat Completion API를 호출합니다.
        Flow-Chat API에서 사용하기 위한 간단한 래퍼 메서드입니다.
        
        Args:
            messages: 메시지 목록 [{"role": "user", "content": "..."}]
            temperature: 응답의 창의성 (0.0-1.0)
            max_tokens: 최대 토큰 수
            response_format: 응답 포맷 (예: {"type": "json_object"})
            
        Returns:
            OpenAI API 응답 객체
        """
        try:
            kwargs = {
                "model": self.default_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            if response_format:
                kwargs["response_format"] = response_format
            
            response = self.client.chat.completions.create(**kwargs)
            return response
        except Exception as e:
            logger.error(f"OpenAI Chat Completion 호출 실패: {str(e)}")
            raise e

# 전역 OpenAI 서비스 인스턴스
openai_service = OpenAIService() 