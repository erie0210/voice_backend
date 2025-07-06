from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, root_validator
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
import json
import time
import logging
from datetime import datetime

from services.openai_service import OpenAIService
from models.api_models import LearnWord

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

class ConversationStage(str, Enum):
    STARTER = "starter"
    PARAPHRASE = "paraphrase"
    FINISHER = "finisher"

class FlowAction(str, Enum):
    PICK_EMOTION = "pick_emotion"
    VOICE_INPUT = "voice_input"

class FlowChatRequest(BaseModel):
    session_id: Optional[str] = None
    action: FlowAction
    user_input: Optional[str] = None
    emotion: Optional[str] = None
    from_lang: str = "KOREAN"
    to_lang: str = "ENGLISH"
    is_tts_enabled: Optional[bool] = None
    topic: Optional[str] = None
    sub_topic: Optional[str] = None
    keyword: Optional[str] = None
    
    # 별칭 지원
    user_language: Optional[str] = None
    ai_language: Optional[str] = None

    @root_validator(pre=True)
    def _alias_languages(cls, values):
        if "user_language" in values and "from_lang" not in values:
            values["from_lang"] = values["user_language"]
        if "ai_language" in values and "to_lang" not in values:
            values["to_lang"] = values["ai_language"]
        return values

class FlowChatResponse(BaseModel):
    session_id: str
    stage: ConversationStage
    response_text: str
    audio_url: Optional[str] = None
    target_words: Optional[List[LearnWord]] = None
    completed: bool = False

class ConversationSession:
    def __init__(self, session_id: str, emotion: str, from_lang: str, to_lang: str, topic: str = None, sub_topic: str = None, keyword: str = None):
        self.session_id = session_id
        self.emotion = emotion
        self.from_lang = from_lang
        self.to_lang = to_lang
        self.topic = topic
        self.sub_topic = sub_topic
        self.keyword = keyword
        self.stage = ConversationStage.STARTER
        self.learned_expressions = []
        self.user_input_count = 0

# 메모리 기반 세션 저장소
sessions: Dict[str, ConversationSession] = {}

def get_openai_service():
    return OpenAIService()

@router.post("/flow-chat", response_model=FlowChatResponse)
async def flow_chat(
    request: FlowChatRequest,
    http_request: Request,
    openai_service: OpenAIService = Depends(get_openai_service)
):
    """Flow-Chat API: 단순화된 언어학습 시스템"""
    
    logger.info(f"[FLOW_API] Action: {request.action} | Session: {request.session_id}")
    
    try:
        # 새 세션 생성
        if request.action == FlowAction.PICK_EMOTION:
            if not request.emotion:
                raise HTTPException(status_code=400, detail="Emotion is required")
            
            session_id = str(uuid.uuid4())
            session = ConversationSession(
                session_id=session_id,
                emotion=request.emotion.lower(),
                from_lang=request.from_lang,
                to_lang=request.to_lang,
                topic=request.topic,
                sub_topic=request.sub_topic,
                keyword=request.keyword
            )
            sessions[session_id] = session
            
            # OpenAI 시작 응답 생성
            response_text, audio_url = await _generate_starter_response(session, openai_service, request.is_tts_enabled)
            
            return FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=audio_url,
                completed=False
            )
        
        # 음성 입력 처리
        elif request.action == FlowAction.VOICE_INPUT:
            if not request.session_id or request.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            if not request.user_input:
                raise HTTPException(status_code=400, detail="User input is required")
            
            session = sessions[request.session_id]
            session.user_input_count += 1
            
            # 7회째 입력이면 완료
            if session.user_input_count >= 7:
                response_text, audio_url = await _generate_finisher_response(session, openai_service, request.is_tts_enabled)
                return FlowChatResponse(
                    session_id=session.session_id,
                    stage=ConversationStage.FINISHER,
                    response_text=response_text,
                    audio_url=audio_url,
                    completed=True
                )
            
            # Paraphrase 응답 생성
            response_text, learned_expressions, audio_url = await _generate_paraphrase_response(
                session, request.user_input, openai_service, request.is_tts_enabled
            )
            
            session.learned_expressions = learned_expressions
            
            return FlowChatResponse(
                session_id=session.session_id,
                stage=ConversationStage.PARAPHRASE,
                response_text=response_text,
                audio_url=audio_url,
                target_words=learned_expressions,
                completed=False
            )
        
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FLOW_ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def _generate_starter_response(session: ConversationSession, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, Optional[str]]:
    """시작 응답 생성"""
    
    # 간단한 시작 메시지
    if session.from_lang.lower() == "korean":
        response_text = f"안녕하세요! {session.emotion} 감정에 대해 이야기해봐요. 최근 경험을 말해주세요."
    else:
        response_text = f"Hello! Let's talk about {session.emotion} feelings. Tell me about your recent experience."
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_TTS] Generated audio for starter")
        except Exception as e:
            logger.error(f"[FLOW_TTS_ERROR] {str(e)}")
    
    return response_text, audio_url

async def _generate_paraphrase_response(session: ConversationSession, user_input: str, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, List[LearnWord], Optional[str]]:
    """Paraphrase 응답 및 학습 표현 생성"""
    
    # OpenAI 프롬프트 생성
    prompt = f"""
    User said: "{user_input}"
    User is learning {session.to_lang}. 
    Response should be in **3 short sentences** in mixed language.
    Create a response in mixed language of {session.from_lang} but replace words, expressions, idioms, slang, etc. with {session.to_lang}.
    
    response structure:
    - Empathetic reaction to user's feeling (if needed)
    - Paraphrase user's input in {session.to_lang} using words, slang, idioms, and expressions.
    - Then provide 3 {session.to_lang} expressions used in your paraphrase response.
    
    Context: Focus on {session.keyword if session.keyword != 'ANYTHING' else 'general conversation'} topic{f', specifically {session.sub_topic}' if session.sub_topic else ''}{f', incorporating the keyword "{session.keyword}"' if session.keyword else ''}.
    
    Respond in JSON format:
    {{
        "response": "your mixed language response here",
        "learned_expressions": [
            {{"word": "{session.to_lang} expression", "meaning": "{session.from_lang} meaning", "pronunciation": "pronunciation", "example": "example sentence in {session.to_lang}"}}
        ]
    }}
    """
    
    logger.info(f"[FLOW_PROMPT] Generated prompt for paraphrase")
    logger.info(f"[FLOW_PROMPT_CONTENT] {prompt}")
    
    try:
        # OpenAI 호출
        response = await openai_service.get_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content.strip()
        
        logger.info(f"[FLOW_OPENAI_RESPONSE] {content}")
        
        # JSON 파싱
        parsed = json.loads(content)
        response_text = parsed.get("response", "")
        learned_expressions_data = parsed.get("learned_expressions", [])
        
        # LearnWord 객체 생성
        learned_expressions = []
        for expr_data in learned_expressions_data:
            word = expr_data.get("word", "").strip()
            meaning = expr_data.get("meaning", "").strip()
            pronunciation = expr_data.get("pronunciation", "").strip()
            example = expr_data.get("example", "").strip()
            
            if word:
                learned_expressions.append(LearnWord(
                    word=word,
                    meaning=meaning,
                    pronunciation=pronunciation,
                    example=example
                ))
        
    except Exception as e:
        logger.error(f"[FLOW_OPENAI_ERROR] {str(e)}")
        # Fallback
        response_text = f"That's interesting! Please tell me more about your {session.emotion} experience."
        learned_expressions = [
            LearnWord(
                word=f"I feel {session.emotion}",
                meaning=f"나는 {session.emotion}을 느껴요" if session.from_lang.lower() == "korean" else f"I am feeling {session.emotion}",
                pronunciation="",
                example=""
            )
        ]
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_TTS] Generated audio for paraphrase")
        except Exception as e:
            logger.error(f"[FLOW_TTS_ERROR] {str(e)}")
    
    return response_text, learned_expressions, audio_url

async def _generate_finisher_response(session: ConversationSession, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, Optional[str]]:
    """완료 응답 생성"""
    
    if session.from_lang.lower() == "korean":
        response_text = f"대화가 끝났습니다! {session.emotion} 감정에 대해 좋은 이야기를 나눴어요. 새로운 표현들을 잘 배우셨습니다!"
    else:
        response_text = f"Great conversation! We had a nice talk about {session.emotion} feelings. You learned some new expressions!"
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_TTS] Generated audio for finisher")
        except Exception as e:
            logger.error(f"[FLOW_TTS_ERROR] {str(e)}")
    
    return response_text, audio_url 