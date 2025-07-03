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
from models.api_models import LanguageCode, LearnWord

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
    target_words: Optional[List[LearnWord]] = None
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
        self.learned_expressions = []  # LearnWord 객체들을 저장
        self.user_answers = []
        self.user_input_count = 0  # 사용자 음성 입력 횟수 카운터
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

# 메모리 기반 세션 저장소 (프로덕션에서는 Redis나 DB 사용)
sessions: Dict[str, ConversationSession] = {}

# 감정별 교육 표현 정의 (가르쳐주려는 표현)
EMOTION_TEACHING_EXPRESSIONS = {
    "happy": [
        {"word": "I'm over the moon", "meaning": "정말 기쁩니다", "pronunciation": "아임 오버 더 문"},
        {"word": "I'm on cloud nine", "meaning": "구름 위에 있는 것 같이 기뻐요", "pronunciation": "아임 온 클라우드 나인"},
        {"word": "I'm thrilled", "meaning": "너무 신나요", "pronunciation": "아임 쓰릴드"}
    ],
    "sad": [
        {"word": "I'm feeling down", "meaning": "기분이 우울해요", "pronunciation": "아임 필링 다운"},
        {"word": "I'm heartbroken", "meaning": "마음이 아픕니다", "pronunciation": "아임 하트브로큰"},
        {"word": "I'm devastated", "meaning": "너무 상심했어요", "pronunciation": "아임 데바스테이티드"}
    ],
    "angry": [
        {"word": "I'm furious", "meaning": "화가 많이 납니다", "pronunciation": "아임 퓨리어스"},
        {"word": "I'm livid", "meaning": "너무 화가 나요", "pronunciation": "아임 리비드"},
        {"word": "I'm outraged", "meaning": "분노하고 있어요", "pronunciation": "아임 아웃레이지드"}
    ],
    "scared": [
        {"word": "I'm terrified", "meaning": "너무 무서워요", "pronunciation": "아임 테리파이드"},
        {"word": "I'm petrified", "meaning": "무서워서 얼어붙었어요", "pronunciation": "아임 페트리파이드"},
        {"word": "I'm shaking with fear", "meaning": "무서워서 떨고 있어요", "pronunciation": "아임 쉐이킹 위드 피어"}
    ],
    "shy": [
        {"word": "I'm bashful", "meaning": "부끄러워요", "pronunciation": "아임 배쉬풀"},
        {"word": "I'm timid", "meaning": "소심해요", "pronunciation": "아임 티미드"},
        {"word": "I'm self-conscious", "meaning": "의식하고 있어요", "pronunciation": "아임 셀프 컨셔스"}
    ],
    "sleepy": [
        {"word": "I'm drowsy", "meaning": "졸려요", "pronunciation": "아임 드라우지"},
        {"word": "I'm exhausted", "meaning": "지쳐있어요", "pronunciation": "아임 이그조스티드"},
        {"word": "I'm worn out", "meaning": "기진맥진해요", "pronunciation": "아임 원 아웃"}
    ],
    "upset": [
        {"word": "I'm distressed", "meaning": "괴로워요", "pronunciation": "아임 디스트레스드"},
        {"word": "I'm troubled", "meaning": "고민이 있어요", "pronunciation": "아임 트러블드"},
        {"word": "I'm bothered", "meaning": "신경쓰여요", "pronunciation": "아임 바더드"}
    ],
    "confused": [
        {"word": "I'm bewildered", "meaning": "당황스러워요", "pronunciation": "아임 비와일더드"},
        {"word": "I'm perplexed", "meaning": "혼란스러워요", "pronunciation": "아임 퍼플렉스드"},
        {"word": "I'm puzzled", "meaning": "의아해요", "pronunciation": "아임 퍼즐드"}
    ],
    "bored": [
        {"word": "I'm uninterested", "meaning": "흥미가 없어요", "pronunciation": "아임 언인터레스티드"},
        {"word": "I'm restless", "meaning": "안절부절못해요", "pronunciation": "아임 레스트리스"},
        {"word": "I'm disengaged", "meaning": "관심이 없어요", "pronunciation": "아임 디스인게이지드"}
    ],
    "love": [
        {"word": "I'm smitten", "meaning": "푹 빠졌어요", "pronunciation": "아임 스미튼"},
        {"word": "I'm infatuated", "meaning": "반해버렸어요", "pronunciation": "아임 인패츄에이티드"},
        {"word": "I'm head over heels", "meaning": "완전히 빠져있어요", "pronunciation": "아임 헤드 오버 힐스"}
    ],
    "proud": [
        {"word": "I'm accomplished", "meaning": "성취감을 느껴요", "pronunciation": "아임 어컴플리쉬드"},
        {"word": "I'm triumphant", "meaning": "승리감을 느껴요", "pronunciation": "아임 트라이엄펀트"},
        {"word": "I'm elated", "meaning": "우쭐해요", "pronunciation": "아임 일레이티드"}
    ],
    "nervous": [
        {"word": "I'm anxious", "meaning": "불안해요", "pronunciation": "아임 앵시어스"},
        {"word": "I'm jittery", "meaning": "초조해요", "pronunciation": "아임 지터리"},
        {"word": "I'm apprehensive", "meaning": "걱정돼요", "pronunciation": "아임 애프리헨시브"}
    ]
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
    """요청 로깅 (요약)"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # 민감한 정보 마스킹
    masked_request = flow_request.dict()
    if masked_request.get("user_input"):
        masked_request["user_input"] = f"{masked_request['user_input'][:20]}..." if len(masked_request["user_input"]) > 20 else masked_request["user_input"]
    
    logger.info(f"[FLOW_API_REQUEST] IP: {client_ip} | User-Agent: {user_agent[:100]} | Request: {masked_request}")

def _log_request_full(request: Request, flow_request: FlowChatRequest, start_time: float):
    """요청 전체 로깅 (상세)"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # 전체 요청 데이터 로깅
    full_request = flow_request.dict()
    
    logger.info(f"[FLOW_API_REQUEST_FULL] ===== REQUEST START =====")
    logger.info(f"[FLOW_API_REQUEST_FULL] IP: {client_ip}")
    logger.info(f"[FLOW_API_REQUEST_FULL] User-Agent: {user_agent}")
    logger.info(f"[FLOW_API_REQUEST_FULL] Headers: {dict(request.headers)}")
    logger.info(f"[FLOW_API_REQUEST_FULL] Method: {request.method}")
    logger.info(f"[FLOW_API_REQUEST_FULL] URL: {request.url}")
    logger.info(f"[FLOW_API_REQUEST_FULL] Request Body: {json.dumps(full_request, ensure_ascii=False, indent=2)}")
    logger.info(f"[FLOW_API_REQUEST_FULL] ===== REQUEST END =====")

def _log_response(flow_request: FlowChatRequest, response: FlowChatResponse, start_time: float, status_code: int = 200):
    """응답 로깅 (요약)"""
    elapsed_time = time.time() - start_time
    
    # 응답 데이터 마스킹
    masked_response = response.dict()
    if masked_response.get("response_text"):
        masked_response["response_text"] = f"{masked_response['response_text'][:50]}..." if len(masked_response["response_text"]) > 50 else masked_response["response_text"]
    
    logger.info(f"[FLOW_API_RESPONSE] Action: {flow_request.action} | Session: {response.session_id} | Stage: {response.stage} | Status: {status_code} | Time: {elapsed_time:.3f}s | Response: {masked_response}")

def _log_response_full(flow_request: FlowChatRequest, response: FlowChatResponse, start_time: float, status_code: int = 200):
    """응답 전체 로깅 (상세)"""
    elapsed_time = time.time() - start_time
    
    # 전체 응답 데이터 로깅
    full_response = response.dict()
    
    logger.info(f"[FLOW_API_RESPONSE_FULL] ===== RESPONSE START =====")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Action: {flow_request.action}")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Session: {response.session_id}")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Stage: {response.stage}")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Status Code: {status_code}")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Elapsed Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_API_RESPONSE_FULL] Response Body: {json.dumps(full_response, ensure_ascii=False, indent=2, default=str)}")
    logger.info(f"[FLOW_API_RESPONSE_FULL] ===== RESPONSE END =====")

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
    """에러 로깅 (상세)"""
    elapsed_time = time.time() - start_time
    
    # 요약 에러 로깅
    logger.error(f"[FLOW_API_ERROR] Action: {flow_request.action} | Session: {flow_request.session_id} | Error: {str(error)} | Time: {elapsed_time:.3f}s")
    
    # 상세 에러 로깅
    logger.error(f"[FLOW_API_ERROR_FULL] ===== ERROR START =====")
    logger.error(f"[FLOW_API_ERROR_FULL] Action: {flow_request.action}")
    logger.error(f"[FLOW_API_ERROR_FULL] Session: {flow_request.session_id}")
    logger.error(f"[FLOW_API_ERROR_FULL] Error Type: {type(error).__name__}")
    logger.error(f"[FLOW_API_ERROR_FULL] Error Message: {str(error)}")
    logger.error(f"[FLOW_API_ERROR_FULL] Elapsed Time: {elapsed_time:.3f}s")
    logger.error(f"[FLOW_API_ERROR_FULL] Request Data: {json.dumps(flow_request.dict(), ensure_ascii=False, indent=2)}")
    logger.error(f"[FLOW_API_ERROR_FULL] ===== ERROR END =====", exc_info=True)

def get_openai_service():
    return OpenAIService()

@router.post("/flow-chat", response_model=FlowChatResponse)
async def flow_chat(
    request: FlowChatRequest,
    http_request: Request,
    openai_service: OpenAIService = Depends(get_openai_service)
):
    """
    Flow-Chat API: 반복 대화 기반 언어학습 시스템
    
    흐름:
    1. starter -> voice_input (사용자 음성 답변 대기)
    2. paraphrase -> next_stage (반응 -> paraphrasing -> 새로운 표현 알려주기 -> 관련된 질문 하기)
    3. 위 과정을 반복 (7회 user_input까지)
    4. finisher (7회째 user_input 후 대화 완료)
    """
    
    start_time = time.time()
    
    # 요청 로깅 (요약 + 상세)
    _log_request(http_request, request, start_time)
    _log_request_full(http_request, request, start_time)
    
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
            
            # 첫 번째 단계: Starter + Prompt cause 통합
            starter_text = STAGE_RESPONSES[ConversationStage.STARTER].get(
                request.emotion.lower(), 
                f"Hello! I can see you're feeling {request.emotion}. Let's talk about it!"
            )
            
            prompt_cause_text = STAGE_RESPONSES[ConversationStage.PROMPT_CAUSE].get(
                request.emotion.lower(),
                f"What made you feel {request.emotion}? Tell me about it!"
            )
            
            # 두 메시지를 자연스럽게 결합
            combined_response = f"{starter_text} {prompt_cause_text}"
            
            response = FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=combined_response,
                audio_url=f"https://voice.kreators.dev/flow_conversations/{request.emotion.lower()}/starter.mp3",
                completed=False,
                next_action="Please tell me about what made you feel this way using voice input"
            )
            
            # 응답 로깅 (요약 + 상세)
            _log_response(request, response, start_time)
            _log_response_full(request, response, start_time)
            
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
            session.learned_expressions = []
            session.user_input_count = 0
            
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
                next_action="Please tell me about what made you feel this way using voice input"
            )
        
        else:
            logger.warning(f"[FLOW_API_VALIDATION] Invalid action: {request.action} for session {request.session_id}")
            raise HTTPException(status_code=400, detail="Invalid action")
        
        # 응답 로깅 (요약 + 상세)
        _log_response(request, response, start_time)
        _log_response_full(request, response, start_time)
        
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
    
    logger.info(f"[FLOW_STAGE_TRANSITION] Session: {session.session_id} | From: {session.stage} | Emotion: {session.emotion} | Input Count: {session.user_input_count}/7")
    
    # STARTER 단계에서는 voice_input으로 직접 진행
    if session.stage == ConversationStage.STARTER:
        response_text = "Please share what made you feel this way using voice input."
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.STARTER,
            response_text=response_text,
            audio_url=None,
            completed=False,
            next_action="Please use voice input to tell me about your feelings"
        )
    
    elif session.stage == ConversationStage.PARAPHRASE:
        # Paraphrase 단계에서 새로운 표현 알려주기 + 관련 질문 생성
        
        # 학습된 표현들을 보여주고 관련 질문 생성
        if session.learned_expressions:
            expressions_text = ""
            for i, expr in enumerate(session.learned_expressions, 1):
                expressions_text += f"{i}. {expr.word} - {expr.meaning} ({expr.pronunciation})\n"
                if expr.example:
                    expressions_text += f"   Example: {expr.example}\n"
        else:
            expressions_text = "No new expressions learned in this round."
        
        # OpenAI로 다음 관련 질문 생성
        next_question_prompt = f"""
        사용자가 {session.emotion} 감정에 대해 대화하고 있습니다. (현재 {session.user_input_count}회차 대화)
        지금까지의 대화 내용: {session.user_answers[-1] if session.user_answers else "없음"}
        
        이 감정과 관련된 새로운 질문을 생성해주세요. 질문은:
        1. 감정을 더 깊이 탐구할 수 있도록 도와주는 질문
        2. 자연스럽고 대화적인 톤
        3. 영어로 작성
        4. 한 문장으로 간단하게
        
        예시:
        - "Can you tell me more about that feeling?"
        - "What happened right before you felt this way?"
        - "How long have you been feeling like this?"
        - "What usually helps when you feel this way?"
        
        질문만 생성해주세요 (추가 설명 없이):
        """
        
        try:
            logger.info(f"[FLOW_NEXT_QUESTION_REQUEST] Session: {session.session_id} | Generating next question")
            question_response = await openai_service.get_chat_completion(
                messages=[{"role": "user", "content": next_question_prompt}],
                temperature=0.7
            )
            next_question = question_response.choices[0].message.content.strip()
            logger.info(f"[FLOW_NEXT_QUESTION_RESPONSE] Session: {session.session_id} | Generated question: {next_question}")
        except Exception as e:
            logger.error(f"[FLOW_NEXT_QUESTION_ERROR] Session: {session.session_id} | Failed: {str(e)}")
            # 폴백 질문들
            fallback_questions = [
                "Can you tell me more about that feeling?",
                "What happened right before you felt this way?",
                "How are you dealing with this emotion?",
                "What usually helps when you feel like this?",
                "Can you describe this feeling in more detail?"
            ]
            next_question = fallback_questions[(session.user_input_count - 1) % len(fallback_questions)]
        
        # 학습 표현 소개 + 다음 질문 결합
        response_text = f"Great! Here are some new expressions for you:\n\n{expressions_text}\n{next_question}"
        
        # 다시 voice_input을 받기 위해 stage는 paraphrase로 유지
        session.stage = ConversationStage.PARAPHRASE
        
        _log_session_activity(session.session_id, "EXPRESSIONS_AND_NEXT_QUESTION", {
            "emotion": session.emotion,
            "user_input_count": session.user_input_count,
            "learned_expressions": [expr.word for expr in session.learned_expressions],
            "next_question": next_question,
            "total_expressions": len(session.learned_expressions)
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PARAPHRASE,
            response_text=response_text,
            audio_url=None,  # 실시간 TTS
            target_words=session.learned_expressions,
            completed=False,
            next_action="Please answer the question using voice input"
        )
    
    else:
        logger.warning(f"[FLOW_STAGE_ERROR] Cannot proceed to next stage from {session.stage} in session {session.session_id}")
        raise HTTPException(status_code=400, detail="Cannot proceed to next stage from current stage")

async def _handle_voice_input(session: ConversationSession, user_input: str, openai_service: OpenAIService) -> FlowChatResponse:
    """음성 입력 처리"""
    
    logger.info(f"[FLOW_VOICE_INPUT] Session: {session.session_id} | Stage: {session.stage} | Input: {user_input[:50]}...")
    
    # 사용자 입력 카운터 증가
    session.user_input_count += 1
    session.user_answers.append(user_input)
    
    logger.info(f"[FLOW_USER_INPUT_COUNT] Session: {session.session_id} | Count: {session.user_input_count}/7")
    
    # 7회째 입력이면 대화 완료
    if session.user_input_count >= 7:
        session.stage = ConversationStage.FINISHER
        response_text = STAGE_RESPONSES[ConversationStage.FINISHER][session.emotion]
        
        _log_session_activity(session.session_id, "CONVERSATION_COMPLETED", {
            "emotion": session.emotion,
            "learned_expressions": [expr.word for expr in session.learned_expressions],
            "user_answers": len(session.user_answers),
            "total_user_inputs": session.user_input_count,
            "final_stage": ConversationStage.FINISHER
        })
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.FINISHER,
            response_text=response_text,
            audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/finisher.mp3",
            completed=True,
            next_action="Conversation completed! Your learned expressions have been saved."
        )
    
    # STARTER 단계 또는 PARAPHRASE 단계에서 voice_input 처리
    if session.stage == ConversationStage.STARTER or session.stage == ConversationStage.PARAPHRASE:
        # Paraphrase 단계로 이동
        session.stage = ConversationStage.PARAPHRASE
        
        # 감정별 교육 표현 선택 (회차별로 다른 표현 선택)
        teaching_expressions = EMOTION_TEACHING_EXPRESSIONS.get(session.emotion, [])
        expression_index = (session.user_input_count - 1) % len(teaching_expressions) if teaching_expressions else 0
        selected_teaching_expression = teaching_expressions[expression_index] if teaching_expressions else {
            "word": "I understand", 
            "meaning": "이해해요", 
            "pronunciation": "아이 언더스탠드"
        }
        
        # OpenAI로 사용자 답변 분석 및 학습 표현 생성
        analysis_prompt = f"""
        사용자가 {session.emotion} 감정에 대해 "{user_input}"라고 말했습니다. (대화 {session.user_input_count}회차)
        
        다음 3개의 학습 표현을 JSON 형태로 생성해주세요:
        1. 사용자 한국어 표현을 영어로 번역한 것 (2개)
        2. 감정 표현을 더 풍부하게 할 수 있는 교육 표현 (1개): "{selected_teaching_expression['word']}"
        
        JSON 형태:
        {{
            "learned_expressions": [
                {{
                    "word": "영어 표현",
                    "meaning": "한국어 의미",
                    "pronunciation": "발음",
                    "example": "예문"
                }}
            ],
            "paraphrase": "사용자의 답변을 공감하면서 교육 표현({selected_teaching_expression['word']})을 자연스럽게 포함한 응답"
        }}
        
        교육 표현의 의미: {selected_teaching_expression['meaning']}
        교육 표현의 발음: {selected_teaching_expression['pronunciation']}
        """
        
        _log_session_activity(session.session_id, "USER_ANSWER_RECEIVED", {
            "emotion": session.emotion,
            "user_input": user_input,
            "user_input_count": session.user_input_count,
            "answer_count": len(session.user_answers),
            "teaching_expression": selected_teaching_expression
        })
        
        try:
            logger.info(f"[FLOW_OPENAI_REQUEST] Session: {session.session_id} | Paraphrasing user input")
            logger.info(f"[FLOW_OPENAI_REQUEST_PROMPT] Session: {session.session_id} | Prompt: {analysis_prompt}")
            
            paraphrase_response = await openai_service.get_chat_completion(
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.7
            )
            response_content = paraphrase_response.choices[0].message.content
            
            logger.info(f"[FLOW_OPENAI_RESPONSE] Session: {session.session_id} | Paraphrase successful")
            logger.info(f"[FLOW_OPENAI_RESPONSE_CONTENT] Session: {session.session_id} | Response: {response_content}")
            
            # JSON 응답 파싱
            try:
                parsed_response = json.loads(response_content)
                learned_expressions_data = parsed_response.get("learned_expressions", [])
                paraphrase_text = parsed_response.get("paraphrase", "")
                
                # LearnWord 객체들 생성
                learned_expressions = []
                for expr_data in learned_expressions_data:
                    learn_word = LearnWord(
                        word=expr_data.get("word", ""),
                        meaning=expr_data.get("meaning", ""),
                        pronunciation=expr_data.get("pronunciation", ""),
                        example=expr_data.get("example", "")
                    )
                    learned_expressions.append(learn_word)
                
                # 교육 표현 추가
                teaching_learn_word = LearnWord(
                    word=selected_teaching_expression["word"],
                    meaning=selected_teaching_expression["meaning"],
                    pronunciation=selected_teaching_expression["pronunciation"],
                    example=f"When you're feeling {session.emotion}, you can say: {selected_teaching_expression['word']}"
                )
                learned_expressions.append(teaching_learn_word)
                
                # 세션에 저장
                session.learned_expressions = learned_expressions
                
                logger.info(f"[FLOW_EXPRESSION_GENERATION] Session: {session.session_id} | Generated {len(learned_expressions)} expressions")
                
            except json.JSONDecodeError:
                logger.error(f"[FLOW_JSON_PARSE_ERROR] Session: {session.session_id} | Failed to parse JSON response")
                # 폴백 처리
                paraphrase_text = f"I hear that you're feeling {session.emotion} because {user_input}. That's completely understandable. {selected_teaching_expression['word']} - that's a great way to express how you feel!"
                
                # 기본 학습 표현 생성
                learned_expressions = [
                    LearnWord(
                        word="I feel",
                        meaning="나는 느낍니다",
                        pronunciation="아이 필",
                        example="I feel happy when I see my friends."
                    ),
                    LearnWord(
                        word="because",
                        meaning="왜냐하면",
                        pronunciation="비코즈",
                        example="I'm sad because it's raining."
                    ),
                    LearnWord(
                        word=selected_teaching_expression["word"],
                        meaning=selected_teaching_expression["meaning"],
                        pronunciation=selected_teaching_expression["pronunciation"],
                        example=f"When you're feeling {session.emotion}, you can say: {selected_teaching_expression['word']}"
                    )
                ]
                session.learned_expressions = learned_expressions
                
        except Exception as e:
            logger.error(f"[FLOW_OPENAI_ERROR] Session: {session.session_id} | Paraphrase failed: {str(e)}")
            # 폴백 처리
            paraphrase_text = f"I understand you're feeling {session.emotion}. Let me teach you how to express this better using: {selected_teaching_expression['word']}"
            
            # 기본 학습 표현 생성
            learned_expressions = [
                LearnWord(
                    word="I feel",
                    meaning="나는 느낍니다",
                    pronunciation="아이 필",
                    example="I feel happy when I see my friends."
                ),
                LearnWord(
                    word="because",
                    meaning="왜냐하면",
                    pronunciation="비코즈",
                    example="I'm sad because it's raining."
                ),
                LearnWord(
                    word=selected_teaching_expression["word"],
                    meaning=selected_teaching_expression["meaning"],
                    pronunciation=selected_teaching_expression["pronunciation"],
                    example=f"When you're feeling {session.emotion}, you can say: {selected_teaching_expression['word']}"
                )
            ]
            session.learned_expressions = learned_expressions
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PARAPHRASE,
            response_text=paraphrase_text,
            audio_url=None,  # 실시간 TTS
            target_words=session.learned_expressions,
            completed=False,
            next_action="Use next_stage to learn new expressions and get next question"
        )
    
    else:
        logger.warning(f"[FLOW_VOICE_INPUT_ERROR] Voice input not expected at stage {session.stage} in session {session.session_id}")
        raise HTTPException(status_code=400, detail="Voice input not expected at current stage")

@router.get("/flow-chat/session/{session_id}")
async def get_session_info(session_id: str, request: Request):
    """세션 정보 조회"""
    start_time = time.time()
    
    # 요청 로깅
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info(f"[FLOW_SESSION_INFO_REQUEST] Session: {session_id} | IP: {client_ip}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] ===== GET SESSION REQUEST START =====")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] Session ID: {session_id}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] IP: {client_ip}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] User-Agent: {user_agent}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] Headers: {dict(request.headers)}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] Method: {request.method}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] URL: {request.url}")
    logger.info(f"[FLOW_SESSION_INFO_REQUEST_FULL] ===== GET SESSION REQUEST END =====")
    
    if session_id not in sessions:
        logger.warning(f"[FLOW_SESSION_NOT_FOUND] Session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    response_data = {
        "session_id": session.session_id,
        "emotion": session.emotion,
        "stage": session.stage,
        "learned_expressions": [expr.dict() for expr in session.learned_expressions],
        "user_answers": session.user_answers,
        "user_input_count": session.user_input_count,
        "max_inputs": 7,
        "created_at": session.created_at,
        "updated_at": session.updated_at
    }
    
    elapsed_time = time.time() - start_time
    
    # 응답 로깅 (요약 + 상세)
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE] Session: {session_id} | Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] ===== GET SESSION RESPONSE START =====")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] Session: {session_id}")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] Status Code: 200")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] Elapsed Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] Response Body: {json.dumps(response_data, ensure_ascii=False, indent=2, default=str)}")
    logger.info(f"[FLOW_SESSION_INFO_RESPONSE_FULL] ===== GET SESSION RESPONSE END =====")
    
    return response_data

@router.delete("/flow-chat/session/{session_id}")
async def delete_session(session_id: str, request: Request):
    """세션 삭제"""
    start_time = time.time()
    
    # 요청 로깅
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST] Session: {session_id} | IP: {client_ip}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] ===== DELETE SESSION REQUEST START =====")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] Session ID: {session_id}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] IP: {client_ip}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] User-Agent: {user_agent}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] Headers: {dict(request.headers)}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] Method: {request.method}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] URL: {request.url}")
    logger.info(f"[FLOW_SESSION_DELETE_REQUEST_FULL] ===== DELETE SESSION REQUEST END =====")
    
    if session_id not in sessions:
        logger.warning(f"[FLOW_SESSION_DELETE_NOT_FOUND] Session: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 세션 삭제 전 정보 로깅
    session = sessions[session_id]
    _log_session_activity(session_id, "SESSION_DELETED", {
        "emotion": session.emotion,
        "stage": session.stage,
        "learned_expressions": [expr.word for expr in session.learned_expressions],
        "user_answers": len(session.user_answers),
        "user_input_count": session.user_input_count,
        "duration": (datetime.now() - session.created_at).total_seconds()
    })
    
    del sessions[session_id]
    
    response_data = {"message": "Session deleted successfully"}
    elapsed_time = time.time() - start_time
    
    # 응답 로깅 (요약 + 상세)
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE] Session: {session_id} | Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] ===== DELETE SESSION RESPONSE START =====")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] Session: {session_id}")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] Status Code: 200")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] Elapsed Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] Response Body: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
    logger.info(f"[FLOW_SESSION_DELETE_RESPONSE_FULL] ===== DELETE SESSION RESPONSE END =====")
    
    return response_data

@router.get("/flow-chat/emotions")
async def get_available_emotions(request: Request):
    """사용 가능한 감정 목록 조회"""
    start_time = time.time()
    
    # 요청 로깅
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info(f"[FLOW_EMOTIONS_REQUEST] IP: {client_ip}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] ===== GET EMOTIONS REQUEST START =====")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] IP: {client_ip}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] User-Agent: {user_agent}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] Headers: {dict(request.headers)}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] Method: {request.method}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] URL: {request.url}")
    logger.info(f"[FLOW_EMOTIONS_REQUEST_FULL] ===== GET EMOTIONS REQUEST END =====")
    
    response_data = {
        "emotions": list(EMOTION_TEACHING_EXPRESSIONS.keys()),
        "teaching_expressions_preview": {
            emotion: [expr["word"] for expr in expressions[:2]] 
            for emotion, expressions in EMOTION_TEACHING_EXPRESSIONS.items()
        }
    }
    
    elapsed_time = time.time() - start_time
    
    # 응답 로깅 (요약 + 상세)
    logger.info(f"[FLOW_EMOTIONS_RESPONSE] Time: {elapsed_time:.3f}s | Emotions: {len(response_data['emotions'])}")
    logger.info(f"[FLOW_EMOTIONS_RESPONSE_FULL] ===== GET EMOTIONS RESPONSE START =====")
    logger.info(f"[FLOW_EMOTIONS_RESPONSE_FULL] Status Code: 200")
    logger.info(f"[FLOW_EMOTIONS_RESPONSE_FULL] Elapsed Time: {elapsed_time:.3f}s")
    logger.info(f"[FLOW_EMOTIONS_RESPONSE_FULL] Response Body: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
    logger.info(f"[FLOW_EMOTIONS_RESPONSE_FULL] ===== GET EMOTIONS RESPONSE END =====")
    
    return response_data 