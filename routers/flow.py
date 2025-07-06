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
    TEXT_INPUT = "text_input"

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
    
    # 요청 JSON 로깅
    request_json = request.dict()
    logger.info(f"[FLOW_REQUEST_JSON] {json.dumps(request_json, ensure_ascii=False)}")
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
            response_text, learned_expressions, audio_url = await _generate_starter_response(session, openai_service, request.is_tts_enabled)
            
            # 세션에 학습 표현 저장
            session.learned_expressions = learned_expressions
            
            return FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=audio_url,
                target_words=learned_expressions,  # 시작 단계에서도 학습 표현 제공
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
        
        # 텍스트 입력 처리 (음성 생성 없음)
        elif request.action == FlowAction.TEXT_INPUT:
            if not request.session_id or request.session_id not in sessions:
                raise HTTPException(status_code=404, detail="Session not found")
            if not request.user_input:
                raise HTTPException(status_code=400, detail="User input is required")
            
            session = sessions[request.session_id]
            session.user_input_count += 1
            
            logger.info(f"[FLOW_TEXT_INPUT] Processing text input without TTS generation")
            
            # 7회째 입력이면 완료 (텍스트만)
            if session.user_input_count >= 7:
                response_text, _ = await _generate_finisher_response(session, openai_service, False)  # TTS 비활성화
                return FlowChatResponse(
                    session_id=session.session_id,
                    stage=ConversationStage.FINISHER,
                    response_text=response_text,
                    audio_url=None,  # 음성 없음
                    completed=True
                )
            
            # Paraphrase 응답 생성 (텍스트만)
            response_text, learned_expressions, _ = await _generate_paraphrase_response(
                session, request.user_input, openai_service, False  # TTS 비활성화
            )
            
            session.learned_expressions = learned_expressions
            
            return FlowChatResponse(
                session_id=session.session_id,
                stage=ConversationStage.PARAPHRASE,
                response_text=response_text,
                audio_url=None,  # 음성 없음
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

async def _generate_starter_response(session: ConversationSession, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, List[LearnWord], Optional[str]]:
    """시작 응답 생성 - topic과 keyword를 조합한 재미있는 질문 + 학습 표현"""
    
    # topic과 keyword 조합하여 재미있는 질문 + 학습 표현 생성
    logger.info(f"[FLOW_STARTER_DEBUG] === Starter Question + Expressions Generation ===")
    logger.info(f"[FLOW_STARTER_DEBUG] Session - emotion: {session.emotion}, topic: {session.topic}, keyword: {session.keyword}")
    
    # OpenAI 프롬프트로 재미있는 질문과 학습 표현 생성
    question_prompt = f"""
    Create a fun and personal question in {session.from_lang} language and provide 2 {session.to_lang} expressions.
    
    Context:
    - Topic: {session.topic if session.topic else 'general conversation'}
    - Keyword: {session.keyword if session.keyword else 'anything'}
    - User is learning {session.to_lang}
    
    Requirements for Question:
    - Combine the topic and keyword to create an interesting, slightly funny, and personal question (one question only)
    - The question should be relatable and make people think about their own experiences
    - Use casual, friendly tone
    - Ask about a specific situation or experience related to both topic and keyword
    
    Requirements for Expressions:
    - Provide 2 {session.to_lang} expressions, word, idiom, slang, etc. mentioned in the question
    - Each expression should have meaning in {session.from_lang}, pronunciation, and example
    
    Examples:
    - Topic: food, Keyword: rain → Question: "비 오는 날에 특별히 먹고 싶어지는 음식이 있나요? 왜 그런 기분이 드는 것 같아요?"
    
    Respond in JSON format:
    {{
        "question": "your question here",
        "learned_expressions": [
            {{"word": "{session.to_lang} expression", "meaning": "{session.from_lang} meaning", "pronunciation": "pronunciation", "example": "example sentence in {session.to_lang}"}}
        ]
    }}
    """
    
    logger.info(f"[FLOW_STARTER_DEBUG] === Question + Expressions Generation Prompt ===")
    logger.info(f"[FLOW_STARTER_PROMPT] {question_prompt}")
    logger.info(f"[FLOW_STARTER_DEBUG] === End of Starter Prompt ===")
    
    try:
        # OpenAI 호출로 질문과 학습 표현 생성
        logger.info(f"[FLOW_STARTER_OPENAI] Calling OpenAI to generate starter question and expressions")
        response = await openai_service.get_chat_completion(
            messages=[{"role": "user", "content": question_prompt}],
            temperature=0.8,  # 더 창의적인 질문을 위해 temperature 높임
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content.strip()
        
        logger.info(f"[FLOW_STARTER_RESPONSE] Generated response: {content}")
        
        # JSON 파싱
        parsed = json.loads(content)
        response_text = parsed.get("question", "")
        learned_expressions_data = parsed.get("learned_expressions", [])
        
        logger.info(f"[FLOW_STARTER_PARSED] Question: {response_text}")
        logger.info(f"[FLOW_STARTER_PARSED] Expressions Count: {len(learned_expressions_data)}")
        
        # LearnWord 객체 생성
        learned_expressions = []
        for i, expr_data in enumerate(learned_expressions_data):
            word = expr_data.get("word", "").strip()
            meaning = expr_data.get("meaning", "").strip()
            pronunciation = expr_data.get("pronunciation", "").strip()
            example = expr_data.get("example", "").strip()
            
            logger.info(f"[FLOW_STARTER_EXPRESSION_{i+1}] Word: {word}, Meaning: {meaning}")
            
            if word:
                learned_expressions.append(LearnWord(
                    word=word,
                    meaning=meaning,
                    pronunciation=pronunciation,
                    example=example
                ))
        
        logger.info(f"[FLOW_STARTER_FINAL] Generated {len(learned_expressions)} expressions")
        
    except Exception as e:
        logger.error(f"[FLOW_STARTER_ERROR] Question and expressions generation failed: {str(e)}")
        # Fallback 질문들과 기본 표현 - 언어 무관 처리
        if session.topic and session.keyword:
            response_text = f"Hello! Let's talk about {session.topic} and {session.keyword}. Have you had any special experience with {session.keyword}? How did you feel?"
        else:
            response_text = f"Hello! Let's talk about {session.emotion} feelings. Tell me about your recent experience with that emotion."
        
        # 기본 학습 표현 생성
        learned_expressions = [
            LearnWord(
                word=f"I like {session.keyword}" if session.keyword else f"I feel {session.emotion}",
                meaning=f"I like {session.keyword}" if session.keyword else f"I am feeling {session.emotion}",
                pronunciation="",
                example=""
            ),
            LearnWord(
                word="experience",
                meaning="경험/체험",
                pronunciation="",
                example="Tell me about your experience."
            )
        ]
        
        logger.info(f"[FLOW_STARTER_FALLBACK] Using fallback question and expressions")
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            logger.info(f"[FLOW_STARTER_TTS] Generating TTS in {tts_language} for question")
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_STARTER_TTS] Generated audio URL: {audio_url}")
        except Exception as e:
            logger.error(f"[FLOW_STARTER_TTS_ERROR] TTS generation failed: {str(e)}")
    else:
        logger.info(f"[FLOW_STARTER_TTS] TTS disabled for starter question")
    
    return response_text, learned_expressions, audio_url

async def _generate_paraphrase_response(session: ConversationSession, user_input: str, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, List[LearnWord], Optional[str]]:
    """Paraphrase 응답 및 학습 표현 생성"""
    
    # 프롬프트 구성 요소 디버깅 로깅
    logger.info(f"[FLOW_PROMPT_DEBUG] === OpenAI Prompt Construction ===")
    logger.info(f"[FLOW_PROMPT_DEBUG] User Input: '{user_input}'")
    logger.info(f"[FLOW_PROMPT_DEBUG] Session - from_lang: {session.from_lang}, to_lang: {session.to_lang}")
    logger.info(f"[FLOW_PROMPT_DEBUG] Session - emotion: {session.emotion}, topic: {session.topic}, sub_topic: {session.sub_topic}, keyword: {session.keyword}")
    
    # Context 구성
    context_parts = []
    if session.keyword and session.keyword != 'ANYTHING':
        context_parts.append(f"keyword: {session.keyword}")
    if session.sub_topic:
        context_parts.append(f"sub_topic: {session.sub_topic}")
    
    context_text = f"Focus on {session.keyword if session.keyword != 'ANYTHING' else 'general conversation'} topic"
    if session.sub_topic:
        context_text += f", specifically {session.sub_topic}"
    if session.keyword and session.keyword != 'ANYTHING':
        context_text += f", incorporating the keyword \"{session.keyword}\""
    
    logger.info(f"[FLOW_PROMPT_DEBUG] Context Text: {context_text}")
    
    # OpenAI 프롬프트 생성
    prompt = f"""
    User said: "{user_input}"
    User is learning {session.to_lang}. 
    Response should be in **3 short sentences** in mixed language.
    Mixed language: main language is {session.from_lang} but replace some important words, expressions, idioms, slang, etc. with {session.to_lang}.
    
    response structure:
    - Empathetic reaction to user's feeling (if needed)
    - Paraphrase user's input in {session.to_lang} using words, slang, idioms, and expressions.
    - Then provide 3 {session.to_lang} expressions used in your paraphrase response.
    - Include emojis in your response.
    - Keep conversation flow.
    - A little bit funny.

    One sentecne should include 1-2 {session.to_lang} expressions.
    For example, from_lang: Korean, to_lang: English, response should be "고양이가 노는 모습 so adorable 하지, 고양이가 골골거리는 건 purring 이라고 해. Most favorite 고양이 color는 뭐야?"

    Context: {context_text}.
    
    Respond in JSON format:
    {{
        "response": "your mixed language response here",
        "learned_expressions": [
            {{"word": "{session.to_lang} expression", "meaning": "{session.from_lang} meaning", "pronunciation": "pronunciation", "example": "example sentence in {session.to_lang}"}}
        ]
    }}
    """
    
    logger.info(f"[FLOW_PROMPT_DEBUG] === Final Prompt to OpenAI ===")
    logger.info(f"[FLOW_PROMPT_CONTENT] {prompt}")
    logger.info(f"[FLOW_PROMPT_DEBUG] === End of Prompt ===")
    
    try:
        # OpenAI 호출
        logger.info(f"[FLOW_OPENAI_CALL] Calling OpenAI with temperature=0.7, JSON format")
        response = await openai_service.get_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content.strip()
        
        logger.info(f"[FLOW_OPENAI_RESPONSE] Raw Response: {content}")
        
        # JSON 파싱
        parsed = json.loads(content)
        response_text = parsed.get("response", "")
        learned_expressions_data = parsed.get("learned_expressions", [])
        
        logger.info(f"[FLOW_OPENAI_PARSED] Response Text: {response_text}")
        logger.info(f"[FLOW_OPENAI_PARSED] Learned Expressions Count: {len(learned_expressions_data)}")
        
        # LearnWord 객체 생성
        learned_expressions = []
        for i, expr_data in enumerate(learned_expressions_data):
            word = expr_data.get("word", "").strip()
            meaning = expr_data.get("meaning", "").strip()
            pronunciation = expr_data.get("pronunciation", "").strip()
            example = expr_data.get("example", "").strip()
            
            logger.info(f"[FLOW_EXPRESSION_{i+1}] Word: {word}, Meaning: {meaning}")
            
            if word:
                learned_expressions.append(LearnWord(
                    word=word,
                    meaning=meaning,
                    pronunciation=pronunciation,
                    example=example
                ))
        
        logger.info(f"[FLOW_FINAL_EXPRESSIONS] Generated {len(learned_expressions)} valid expressions")
        
    except Exception as e:
        logger.error(f"[FLOW_OPENAI_ERROR] OpenAI call failed: {str(e)}")
        # Fallback - 언어 무관 처리
        response_text = f"That's interesting! Please tell me more about your {session.emotion} experience."
        learned_expressions = [
            LearnWord(
                word=f"I like {session.keyword}" if session.keyword else f"I feel {session.emotion}",
                meaning=f"I like {session.keyword}" if session.keyword else f"I am feeling {session.emotion}",
                pronunciation="",
                example=""
            )
        ]
        logger.info(f"[FLOW_FALLBACK] Using fallback response and expressions")
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            logger.info(f"[FLOW_TTS_DEBUG] Generating TTS in {tts_language} for: {response_text[:50]}...")
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_TTS] Generated audio URL: {audio_url}")
        except Exception as e:
            logger.error(f"[FLOW_TTS_ERROR] TTS generation failed: {str(e)}")
    else:
        logger.info(f"[FLOW_TTS] TTS disabled, skipping audio generation")
    
    return response_text, learned_expressions, audio_url

async def _generate_finisher_response(session: ConversationSession, openai_service: OpenAIService, is_tts_enabled: Optional[bool]) -> tuple[str, Optional[str]]:
    """완료 응답 생성"""
    
    # 언어 무관 완료 메시지
    response_text = f"Great conversation! We had a nice talk about {session.emotion} feelings. You learned some new expressions!"
    
    # TTS 생성
    audio_url = None
    if is_tts_enabled:
        try:
            tts_language = session.from_lang.capitalize()
            logger.info(f"[FLOW_FINISHER_TTS] Generating TTS in {tts_language} for finisher")
            audio_url, _ = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_FINISHER_TTS] Generated audio URL: {audio_url}")
        except Exception as e:
            logger.error(f"[FLOW_FINISHER_TTS_ERROR] TTS generation failed: {str(e)}")
    else:
        logger.info(f"[FLOW_FINISHER_TTS] TTS disabled for finisher")
    
    return response_text, audio_url 