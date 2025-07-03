from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
import json
import time
import logging
from datetime import datetime

from services.openai_service import OpenAIService
from models.api_models import LanguageCode

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

class ConversationStage(str, Enum):
    EMOTION_SELECTION = "emotion_selection"
    STARTER = "starter"
    PROMPT_CAUSE = "prompt_cause"
    USER_ANSWER = "user_answer"
    PARAPHRASE = "paraphrase"
    EMPATHY_VOCAB = "empathy_vocab"
    USER_REPEAT = "user_repeat"
    FINISHER = "finisher"
    COMPLETED = "completed"

class FlowAction(str, Enum):
    PICK_EMOTION = "pick_emotion"
    NEXT_STAGE = "next_stage"
    VOICE_INPUT = "voice_input"
    RESTART = "restart"

class FlowChatRequest(BaseModel):
    session_id: Optional[str] = None
    action: FlowAction
    user_input: Optional[str] = None
    emotion: Optional[str] = None
    from_lang: LanguageCode = LanguageCode.KOREAN
    to_lang: LanguageCode = LanguageCode.ENGLISH

class FlowChatResponse(BaseModel):
    session_id: str
    stage: ConversationStage
    response_text: str
    audio_url: Optional[str] = None
    target_words: Optional[List[str]] = None
    stt_feedback: Optional[Dict[str, Any]] = None
    completed: bool = False
    next_action: Optional[str] = None

class ConversationSession:
    def __init__(self, session_id: str, emotion: str, from_lang: str, to_lang: str):
        self.session_id = session_id
        self.emotion = emotion
        self.from_lang = from_lang
        self.to_lang = to_lang
        self.stage = ConversationStage.STARTER
        self.learned_words = []
        self.user_answers = []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

# 메모리 기반 세션 저장소 (프로덕션에서는 Redis나 DB 사용)
sessions: Dict[str, ConversationSession] = {}

# 감정별 학습 단어 정의
EMOTION_VOCABULARY = {
    "happy": ["joyful", "delighted", "cheerful", "content", "pleased"],
    "sad": ["sorrowful", "melancholy", "disappointed", "heartbroken", "gloomy"],
    "angry": ["furious", "irritated", "annoyed", "outraged", "frustrated"],
    "scared": ["terrified", "anxious", "worried", "nervous", "frightened"],
    "shy": ["bashful", "timid", "reserved", "modest", "self-conscious"],
    "sleepy": ["drowsy", "tired", "exhausted", "weary", "fatigued"],
    "upset": ["distressed", "troubled", "bothered", "agitated", "disturbed"],
    "confused": ["puzzled", "bewildered", "perplexed", "uncertain", "lost"],
    "bored": ["uninterested", "restless", "weary", "disengaged", "listless"],
    "love": ["affectionate", "devoted", "caring", "passionate", "tender"],
    "proud": ["accomplished", "satisfied", "confident", "triumphant", "honored"],
    "nervous": ["anxious", "tense", "uneasy", "jittery", "apprehensive"]
}

# 단계별 응답 템플릿
STAGE_RESPONSES = {
    ConversationStage.STARTER: {
        "happy": "Hi there! I can see you're feeling happy today. That's wonderful! 😊",
        "sad": "Hello. I notice you might be feeling a bit sad. I'm here to listen. 💙",
        "angry": "I can sense you're feeling angry right now. Let's talk about it. 😤",
        "scared": "Hey, I understand you might be feeling scared. You're safe here. 🤗",
        "shy": "Hi! I see you're feeling a bit shy. That's perfectly okay. 😌",
        "sleepy": "Hello there! Feeling sleepy? Let's have a gentle conversation. 😴",
        "upset": "I can tell you're feeling upset. I'm here to help you through this. 💜",
        "confused": "Hi! I sense you're feeling confused about something. Let's figure it out together. 🤔",
        "bored": "Hey! Feeling bored? Let's make this conversation interesting! 🎯",
        "love": "Hello! I can feel the love in your heart. That's beautiful! 💕",
        "proud": "Hi there! I can sense you're feeling proud. That's amazing! 🌟",
        "nervous": "Hello! I notice you're feeling nervous. Take a deep breath with me. 😌"
    },
    ConversationStage.PROMPT_CAUSE: {
        "happy": "What made you feel so happy today? Tell me about it!",
        "sad": "What's making you feel sad right now? I'm here to listen.",
        "angry": "What happened that made you feel angry? Share with me.",
        "scared": "What's making you feel scared? You can tell me about it.",
        "shy": "What's making you feel shy today? It's okay to share.",
        "sleepy": "What's making you feel so sleepy? Long day?",
        "upset": "What's got you feeling upset? I want to understand.",
        "confused": "What's confusing you right now? Let's work through it.",
        "bored": "What's making you feel bored? Let's find something exciting!",
        "love": "What's filling your heart with love? I'd love to hear about it.",
        "proud": "What are you feeling proud about? Tell me your achievement!",
        "nervous": "What's making you feel nervous? Let's talk about it."
    },
    ConversationStage.FINISHER: {
        "happy": "I'm so glad we talked about your happiness! Keep spreading those positive vibes! ✨",
        "sad": "Thank you for sharing your feelings with me. Remember, it's okay to feel sad sometimes. 💙",
        "angry": "I'm proud of you for expressing your anger in a healthy way. You did great! 👏",
        "scared": "You were very brave to talk about your fears. You're stronger than you think! 💪",
        "shy": "You did wonderfully opening up to me. Your shyness is part of what makes you special! 🌸",
        "sleepy": "Thanks for staying awake to chat with me! Hope you get some good rest soon! 😴",
        "upset": "I'm glad you shared what was upsetting you. You're not alone in this. 🤗",
        "confused": "Great job working through your confusion with me! You're learning so much! 🧠",
        "bored": "I hope our conversation made things more interesting for you! 🎉",
        "love": "Your love and warmth really touched my heart. Keep spreading that love! 💕",
        "proud": "Your pride is well-deserved! Keep celebrating your achievements! 🎊",
        "nervous": "You handled your nervousness so well. I'm proud of how you expressed yourself! 🌟"
    }
}

def _log_request(request: Request, flow_request: FlowChatRequest, start_time: float):
    """요청 로깅"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # 민감한 정보 마스킹
    masked_request = flow_request.dict()
    if masked_request.get("user_input"):
        masked_request["user_input"] = f"{masked_request['user_input'][:20]}..." if len(masked_request["user_input"]) > 20 else masked_request["user_input"]
    
    logger.info(f"[FLOW_API_REQUEST] IP: {client_ip} | User-Agent: {user_agent[:100]} | Request: {masked_request}")

def _log_response(flow_request: FlowChatRequest, response: FlowChatResponse, start_time: float, status_code: int = 200):
    """응답 로깅"""
    elapsed_time = time.time() - start_time
    
    # 응답 데이터 마스킹
    masked_response = response.dict()
    if masked_response.get("response_text"):
        masked_response["response_text"] = f"{masked_response['response_text'][:50]}..." if len(masked_response["response_text"]) > 50 else masked_response["response_text"]
    
    logger.info(f"[FLOW_API_RESPONSE] Action: {flow_request.action} | Session: {response.session_id} | Stage: {response.stage} | Status: {status_code} | Time: {elapsed_time:.3f}s | Response: {masked_response}")

def _log_session_activity(session_id: str, activity: str, details: Dict[str, Any] = None):
    """세션 활동 로깅"""
    log_data = {
        "session_id": session_id,
        "activity": activity,
        "timestamp": datetime.now().isoformat()
    }
    if details:
        log_data.update(details)
    
    logger.info(f"[FLOW_SESSION_ACTIVITY] {log_data}")

def _log_error(error: Exception, flow_request: FlowChatRequest, start_time: float):
    """에러 로깅"""
    elapsed_time = time.time() - start_time
    
    logger.error(f"[FLOW_API_ERROR] Action: {flow_request.action} | Session: {flow_request.session_id} | Error: {str(error)} | Time: {elapsed_time:.3f}s", exc_info=True)

def get_openai_service():
    return OpenAIService()

@router.post("/flow-chat", response_model=FlowChatResponse)
async def flow_chat(
    request: FlowChatRequest,
    http_request: Request,
    openai_service: OpenAIService = Depends(get_openai_service)
):
    """
    Flow-Chat API: 7단계 감정 기반 언어학습 대화 시스템
    
    Stage 0: 감정 선택 (UI)
    Stage 1: Starter (사전 생성 음성)
    Stage 2: Prompt cause (사전 생성 음성)  
    Stage 3: User answer (STT)
    Stage 4: Paraphrase + keyword highlight (실시간 TTS)
    Stage 5: Empathy + new vocabulary (사전 생성 음성)
    Stage 6: User repeat & STT check (발음 교정)
    Stage 7: Finisher (사전 생성 음성, 단어장 저장)
    """
    
    start_time = time.time()
    
    # 요청 로깅
    _log_request(http_request, request, start_time)
    
    try:
        # 새 세션 생성 또는 기존 세션 로드
        if request.action == FlowAction.PICK_EMOTION:
            if not request.emotion:
                logger.warning(f"[FLOW_API_VALIDATION] Missing emotion for pick_emotion action")
                raise HTTPException(status_code=400, detail="Emotion is required for pick_emotion action")
            
            session_id = str(uuid.uuid4())
            session = ConversationSession(
                session_id=session_id,
                emotion=request.emotion.lower(),
                from_lang=request.from_lang.value,
                to_lang=request.to_lang.value
            )
            sessions[session_id] = session
            
            # 세션 생성 로깅
            _log_session_activity(session_id, "SESSION_CREATED", {
                "emotion": request.emotion.lower(),
                "from_lang": request.from_lang.value,
                "to_lang": request.to_lang.value
            })
            
            # 첫 번째 단계: Starter
            response_text = STAGE_RESPONSES[ConversationStage.STARTER].get(
                request.emotion.lower(), 
                f"Hello! I can see you're feeling {request.emotion}. Let's talk about it!"
            )
            
            response = FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=f"https://voice.kreators.dev/flow_conversations/{request.emotion.lower()}/starter.mp3",
                completed=False,
                next_action="Listen to the audio and proceed to next stage"
            )
            
            # 응답 로깅
            _log_response(request, response, start_time)
            
            return response
        
        # 기존 세션 처리
        if not request.session_id or request.session_id not in sessions:
            logger.warning(f"[FLOW_API_VALIDATION] Session not found: {request.session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = sessions[request.session_id]
        session.updated_at = datetime.now()
        
        # 세션 접근 로깅
        _log_session_activity(request.session_id, "SESSION_ACCESSED", {
            "current_stage": session.stage,
            "emotion": session.emotion,
            "action": request.action
        })
        
        if request.action == FlowAction.NEXT_STAGE:
            response = await _handle_next_stage(session, openai_service)
            
        elif request.action == FlowAction.VOICE_INPUT:
            if not request.user_input:
                logger.warning(f"[FLOW_API_VALIDATION] Missing user_input for voice_input action in session {request.session_id}")
                raise HTTPException(status_code=400, detail="User input is required for voice_input action")
            
            response = await _handle_voice_input(session, request.user_input, openai_service)
            
        elif request.action == FlowAction.RESTART:
            session.stage = ConversationStage.STARTER
            session.user_answers = []
            session.learned_words = []
            
            # 세션 재시작 로깅
            _log_session_activity(request.session_id, "SESSION_RESTARTED", {
                "emotion": session.emotion
            })
            
            response_text = STAGE_RESPONSES[ConversationStage.STARTER][session.emotion]
            
            response = FlowChatResponse(
                session_id=session.session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/starter.mp3",
                completed=False,
                next_action="Listen to the audio and proceed to next stage"
            )
        
        else:
            logger.warning(f"[FLOW_API_VALIDATION] Invalid action: {request.action} for session {request.session_id}")
            raise HTTPException(status_code=400, detail="Invalid action")
        
        # 응답 로깅
        _log_response(request, response, start_time)
        
        return response
            
    except HTTPException as e:
        # HTTP 예외 로깅
        _log_error(e, request, start_time)
        raise
    except Exception as e:
        # 일반 예외 로깅
        _log_error(e, request, start_time)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def _handle_next_stage(session: ConversationSession, openai_service: OpenAIService) -> FlowChatResponse:
    """다음 단계로 진행"""
    
    logger.info(f"[FLOW_STAGE_TRANSITION] Session: {session.session_id} | From: {session.stage} | Emotion: {session.emotion}")
    
    if session.stage == ConversationStage.STARTER:
        # Stage 2: Prompt cause
        session.stage = ConversationStage.PROMPT_CAUSE
        response_text = STAGE_RESPONSES[ConversationStage.PROMPT_CAUSE][session.emotion]
        
        _log_session_activity(session.session_id, "STAGE_TRANSITION", {
            "from_stage": ConversationStage.STARTER,
            "to_stage": ConversationStage.PROMPT_CAUSE,
            "emotion": session.emotion
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PROMPT_CAUSE,
            response_text=response_text,
            audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/prompt_cause.mp3",
            completed=False,
            next_action="Please answer the question using voice input"
        )
    
    elif session.stage == ConversationStage.USER_ANSWER:
        # Stage 5: Empathy + new vocabulary
        session.stage = ConversationStage.EMPATHY_VOCAB
        
        # 감정별 학습 단어 선택
        vocab_words = EMOTION_VOCABULARY.get(session.emotion, ["wonderful", "amazing", "great"])
        selected_words = vocab_words[:3]  # 3개 단어 선택
        session.learned_words.extend(selected_words)
        
        response_text = f"I understand how you feel. Let me teach you some new words to express {session.emotion}: {', '.join(selected_words)}"
        
        _log_session_activity(session.session_id, "VOCABULARY_LEARNING", {
            "emotion": session.emotion,
            "learned_words": selected_words,
            "total_learned": len(session.learned_words)
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.EMPATHY_VOCAB,
            response_text=response_text,
            audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/empathy_vocab.mp3",
            target_words=selected_words,
            completed=False,
            next_action="Listen to the new vocabulary and try to repeat"
        )
    
    elif session.stage == ConversationStage.USER_REPEAT:
        # Stage 7: Finisher
        session.stage = ConversationStage.FINISHER
        response_text = STAGE_RESPONSES[ConversationStage.FINISHER][session.emotion]
        
        _log_session_activity(session.session_id, "CONVERSATION_COMPLETED", {
            "emotion": session.emotion,
            "learned_words": session.learned_words,
            "user_answers": len(session.user_answers),
            "final_stage": ConversationStage.FINISHER
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.FINISHER,
            response_text=response_text,
            audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/finisher.mp3",
            completed=True,
            next_action="Conversation completed! Your learned words have been saved."
        )
    
    else:
        logger.warning(f"[FLOW_STAGE_ERROR] Cannot proceed to next stage from {session.stage} in session {session.session_id}")
        raise HTTPException(status_code=400, detail="Cannot proceed to next stage from current stage")

async def _handle_voice_input(session: ConversationSession, user_input: str, openai_service: OpenAIService) -> FlowChatResponse:
    """음성 입력 처리"""
    
    logger.info(f"[FLOW_VOICE_INPUT] Session: {session.session_id} | Stage: {session.stage} | Input: {user_input[:50]}...")
    
    if session.stage == ConversationStage.PROMPT_CAUSE:
        # Stage 3: User answer -> Stage 4: Paraphrase
        session.stage = ConversationStage.USER_ANSWER
        session.user_answers.append(user_input)
        
        # OpenAI로 사용자 답변 패러프레이징
        paraphrase_prompt = f"User said: '{user_input}' about feeling {session.emotion}. Please paraphrase this in a supportive way and highlight key emotional words."
        
        _log_session_activity(session.session_id, "USER_ANSWER_RECEIVED", {
            "emotion": session.emotion,
            "user_input": user_input,
            "answer_count": len(session.user_answers)
        })
        
        try:
            logger.info(f"[FLOW_OPENAI_REQUEST] Session: {session.session_id} | Paraphrasing user input")
            paraphrase_response = await openai_service.get_chat_completion(
                messages=[{"role": "user", "content": paraphrase_prompt}],
                temperature=0.7
            )
            response_text = paraphrase_response.choices[0].message.content
            logger.info(f"[FLOW_OPENAI_RESPONSE] Session: {session.session_id} | Paraphrase successful")
        except Exception as e:
            logger.error(f"[FLOW_OPENAI_ERROR] Session: {session.session_id} | Paraphrase failed: {str(e)}")
            response_text = f"I hear that you're feeling {session.emotion} because {user_input}. That's completely understandable."
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PARAPHRASE,
            response_text=response_text,
            audio_url=None,  # 실시간 TTS
            completed=False,
            next_action="Proceed to learn new vocabulary"
        )
    
    elif session.stage == ConversationStage.EMPATHY_VOCAB:
        # Stage 6: User repeat & STT check
        session.stage = ConversationStage.USER_REPEAT
        
        # 발음 체크 (간단한 키워드 매칭)
        learned_words = session.learned_words
        recognized_words = []
        
        for word in learned_words:
            if word.lower() in user_input.lower():
                recognized_words.append(word)
        
        accuracy = len(recognized_words) / len(learned_words) * 100 if learned_words else 0
        
        stt_feedback = {
            "accuracy": accuracy,
            "recognized_words": recognized_words,
            "total_words": len(learned_words),
            "feedback": "Great job!" if accuracy > 70 else "Keep practicing!"
        }
        
        response_text = f"Good effort! You pronounced {len(recognized_words)} out of {len(learned_words)} words correctly."
        
        _log_session_activity(session.session_id, "PRONUNCIATION_CHECK", {
            "emotion": session.emotion,
            "user_input": user_input,
            "learned_words": learned_words,
            "recognized_words": recognized_words,
            "accuracy": accuracy
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.USER_REPEAT,
            response_text=response_text,
            stt_feedback=stt_feedback,
            completed=False,
            next_action="Proceed to finish the conversation"
        )
    
    else:
        logger.warning(f"[FLOW_VOICE_INPUT_ERROR] Voice input not expected at stage {session.stage} in session {session.session_id}")
        raise HTTPException(status_code=400, detail="Voice input not expected at current stage")

@router.get("/flow-chat/session/{session_id}")
async def get_session_info(session_id: str, request: Request):
    """세션 정보 조회"""
    start_time = time.time()
    
    logger.info(f"[FLOW_SESSION_INFO_REQUEST] Session: {session_id} | IP: {request.client.host if request.client else 'unknown'}")
    
    if session_id not in sessions:
        logger.warning(f"[FLOW_SESSION_NOT_FOUND] Session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    response_data = {
        "session_id": session.session_id,
        "emotion": session.emotion,
        "stage": session.stage,
        "learned_words": session.learned_words,
        "user_answers": session.user_answers,
        "created_at": session.created_at,
        "updated_at": session.updated_at
    }
    
    elapsed_time = time.time() - start_time
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE] Session: {session_id} | Time: {elapsed_time:.3f}s | Data: {response_data}")
    
    return response_data

@router.delete("/flow-chat/session/{session_id}")
async def delete_session(session_id: str, request: Request):
    """세션 삭제"""
    start_time = time.time()
    
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST] Session: {session_id} | IP: {request.client.host if request.client else 'unknown'}")
    
    if session_id not in sessions:
        logger.warning(f"[FLOW_SESSION_DELETE_NOT_FOUND] Session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 세션 삭제 전 정보 로깅
    session = sessions[session_id]
    _log_session_activity(session_id, "SESSION_DELETED", {
        "emotion": session.emotion,
        "stage": session.stage,
        "learned_words": session.learned_words,
        "user_answers": len(session.user_answers),
        "duration": (datetime.now() - session.created_at).total_seconds()
    })
    
    del sessions[session_id]
    
    elapsed_time = time.time() - start_time
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE] Session: {session_id} | Time: {elapsed_time:.3f}s")
    
    return {"message": "Session deleted successfully"}

@router.get("/flow-chat/emotions")
async def get_available_emotions(request: Request):
    """사용 가능한 감정 목록 조회"""
    start_time = time.time()
    
    logger.info(f"[FLOW_EMOTIONS_REQUEST] IP: {request.client.host if request.client else 'unknown'}")
    
    response_data = {
        "emotions": list(EMOTION_VOCABULARY.keys()),
        "vocabulary_preview": {
            emotion: words[:2] for emotion, words in EMOTION_VOCABULARY.items()
        }
    }
    
    elapsed_time = time.time() - start_time
    logger.info(f"[FLOW_EMOTIONS_RESPONSE] Time: {elapsed_time:.3f}s | Emotions: {len(response_data['emotions'])}")
    
    return response_data 