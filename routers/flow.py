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
from services.r2_service import R2Service
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
            
            # OpenAI로 시작 응답 생성 (TTS 포함)
            combined_response, audio_url = await _generate_openai_response_with_tts(session, ConversationStage.STARTER, openai_service)
            
            response = FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=combined_response,
                audio_url=audio_url,  # 생성된 TTS 오디오 URL 사용
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
            
            # OpenAI로 재시작 응답 생성 (TTS 포함)
            response_text, audio_url = await _generate_openai_response_with_tts(session, ConversationStage.RESTART, openai_service)
            
            response = FlowChatResponse(
                session_id=session.session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=audio_url,  # 생성된 TTS 오디오 URL 사용
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
    
    # STARTER 단계에서는 voice_input으로 직접 진행 (Mixed language)
    if session.stage == ConversationStage.STARTER:
        # Mixed language로 응답 생성
        response_text = f"{session.emotion} 감정과 관련된 expressions를 배워봐요! 음성으로 최근에 {session.emotion}을 느낀 경험을 이야기해주세요."
        next_action = "감정에 대해 음성으로 이야기해주세요"
        
        # Apply TTS to response_text (Mixed language so English is default)
        audio_url = None
        try:
            tts_language = "English"  # Mixed language는 주로 영어 기반
            audio_url, duration = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_STARTER_TTS_SUCCESS] Session: {session.session_id} | Audio URL: {audio_url} | Duration: {duration:.2f}s")
        except Exception as tts_error:
            logger.error(f"[FLOW_STARTER_TTS_ERROR] Session: {session.session_id} | TTS failed: {str(tts_error)}")
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.STARTER,
            response_text=response_text,
            audio_url=audio_url,  # 생성된 TTS 오디오 URL 사용
            completed=False,
            next_action=next_action
        )
    
    elif session.stage == ConversationStage.PARAPHRASE:
        # Paraphrase 단계에서 학습된 표현들을 보여주고 따라해보라고 말하기
        
        # 학습된 표현들 표시
        if session.learned_expressions:
            expressions_text = ""
            for i, expr in enumerate(session.learned_expressions, 1):
                expressions_text += f"{i}. {expr.word} - {expr.meaning} ({expr.pronunciation})\n"
                if expr.example:
                    expressions_text += f"   Example: {expr.example}\n"
        else:
            expressions_text = "새로운 expressions가 없어요."
        
        # 따라해보라고 말하기 (Mixed language로)
        response_text = f"좋아요! 이런 expressions들을 배워봐요:\n\n{expressions_text}\n위의 expressions들을 따라해보세요! 큰 소리로 말해봐요 😊"
        next_action = "따라해보신 후 음성으로 다음 이야기를 들려주세요"
        
        # 다시 voice_input을 받기 위해 stage는 paraphrase로 유지
        session.stage = ConversationStage.PARAPHRASE
        
        _log_session_activity(session.session_id, "EXPRESSIONS_FOR_REPEAT", {
            "emotion": session.emotion,
            "user_input_count": session.user_input_count,
            "learned_expressions": [expr.word for expr in session.learned_expressions],
            "total_expressions": len(session.learned_expressions)
        })
        
        audio_url = None
        try:
            tts_language = "English"  # Mixed language 주로 영어 기반
            audio_url, duration = await openai_service.text_to_speech(response_text, tts_language)
            logger.info(f"[FLOW_NEXT_STAGE_TTS_SUCCESS] Session: {session.session_id} | Audio URL: {audio_url} | Duration: {duration:.2f}s")
        except Exception as tts_error:
            logger.error(f"[FLOW_NEXT_STAGE_TTS_ERROR] Session: {session.session_id} | TTS failed: {str(tts_error)}")
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PARAPHRASE,
            response_text=response_text,
            audio_url=audio_url,  # 생성된 TTS 오디오 URL 사용
            target_words=session.learned_expressions,
            completed=False,
            next_action=next_action
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
        
        # OpenAI로 완료 응답 생성 (TTS 포함)
        response_text, audio_url = await _generate_openai_response_with_tts(session, ConversationStage.FINISHER, openai_service)
        
        _log_session_activity(session.session_id, "CONVERSATION_COMPLETED", {
            "emotion": session.emotion,
            "learned_expressions": [expr.word for expr in session.learned_expressions],
            "user_answers": len(session.user_answers),
            "total_user_inputs": session.user_input_count,
            "final_stage": ConversationStage.FINISHER
        })
        
        completion_action = "Conversation completed! Your learned expressions have been saved."
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.FINISHER,
            response_text=response_text,
            audio_url=audio_url,  # 생성된 TTS 오디오 URL 사용
            completed=True,
            next_action=completion_action
        )
    
    # STARTER 단계 또는 PARAPHRASE 단계에서 voice_input 처리
    if session.stage == ConversationStage.STARTER or session.stage == ConversationStage.PARAPHRASE:
        # Paraphrase 단계로 이동
        session.stage = ConversationStage.PARAPHRASE
        
        # 언어 설정 - Mixed language 사용
        mixed_language = f"Mixed {session.from_lang}-{session.to_lang}"
        user_language = "Korean" if session.from_lang == "korean" else session.from_lang 
        ai_language = "English" if session.to_lang == "english" else session.to_lang
        
        # 단순화된 단일 OpenAI 호출: 응답과 학습 표현을 한 번에 생성
        unified_prompt = f"""
        User said: "{user_input}" (language study topic: {session.emotion})
        Response should be in {mixed_language}
        Response should be 3-4 short sentences. 
        
        Create a response in {mixed_language} with steps:
        - Empathetic reaction to user's feeling (if needed)
        - Introduce related {ai_language} expressions 
        - Paraphrase user's feeling in {ai_language}
        
        Then provide 2 {ai_language} expressions used in your paraphrase response.
        
        Respond in JSON format:
        {{
            "response": "your mixed language response here",
            "learned_expressions": [
                {{"word": "expression", "meaning": "{user_language} meaning", "pronunciation": "pronunciation", "example": "example sentence"}}
            ]
        }}
        """
        
        _log_session_activity(session.session_id, "USER_ANSWER_RECEIVED", {
            "emotion": session.emotion,
            "user_input": user_input,
            "user_input_count": session.user_input_count,
            "answer_count": len(session.user_answers)
        })
        
        try:
            logger.info(f"[FLOW_UNIFIED_REQUEST] Session: {session.session_id} | Generating unified response")
            
            # 단일 OpenAI 호출로 응답과 표현 생성
            unified_response = await openai_service.get_chat_completion(
                messages=[{"role": "user", "content": unified_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            unified_content = unified_response.choices[0].message.content.strip()
            
            logger.info(f"[FLOW_UNIFIED_SUCCESS] Session: {session.session_id} | Generated unified response")
            logger.info(f"[FLOW_UNIFIED_CONTENT] Session: {session.session_id} | Response: {unified_content}")
            
            # JSON 응답 파싱
            parsed_response = json.loads(unified_content)
            paraphrase_text = parsed_response.get("response", "")
            learned_expressions_data = parsed_response.get("learned_expressions", [])
            
            # LearnWord 객체들 생성
            learned_expressions = []
            for expr_data in learned_expressions_data:
                word = expr_data.get("word", "").replace('**', '').replace('##', '').strip()
                meaning = expr_data.get("meaning", "").replace('**', '').replace('##', '').strip()
                pronunciation = expr_data.get("pronunciation", "").replace('**', '').replace('##', '').strip()
                example = expr_data.get("example", "").replace('**', '').replace('##', '').strip()
                
                if word:  # 빈 단어 제외
                    learn_word = LearnWord(
                        word=word,
                        meaning=meaning,
                        pronunciation=pronunciation,
                        example=example
                    )
                    learned_expressions.append(learn_word)
            
            # 세션에 저장
            session.learned_expressions = learned_expressions
            
            logger.info(f"[FLOW_EXPRESSION_GENERATION] Session: {session.session_id} | Generated {len(learned_expressions)} expressions")
            
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[FLOW_UNIFIED_ERROR] Session: {session.session_id} | Unified call failed: {str(e)}")
            
            # 간단한 fallback 처리
            paraphrase_text = f"아, {session.emotion} 감정이시군요! 정말 {user_input}하셨을 때 그런 기분이 들었을 것 같아요. 'I feel {session.emotion}'라고 말할 수 있어요. 다른 경험도 더 얘기해주세요!"
            
            # 기본 학습 표현 생성
            learned_expressions = [
                LearnWord(
                    word=f"I feel {session.emotion}",
                    meaning=f"나는 {session.emotion}을 느껴요",
                    pronunciation=f"아이 필 {session.emotion}",
                    example=f"I feel {session.emotion} when good things happen."
                ),
                LearnWord(
                    word="when",
                    meaning="~할 때",
                    pronunciation="웬",
                    example="I feel happy when I see my friends."
                ),
                LearnWord(
                    word="experience",
                    meaning="경험",
                    pronunciation="익스피리언스",
                    example="Tell me about your experience."
                )
            ]
            session.learned_expressions = learned_expressions
        
        # TTS 처리
        audio_url = None
        try:
            tts_language = "English"  # Mixed language는 주로 영어 기반
            audio_url, duration = await openai_service.text_to_speech(paraphrase_text, tts_language)
            logger.info(f"[FLOW_PARAPHRASE_TTS_SUCCESS] Session: {session.session_id} | Audio URL: {audio_url} | Duration: {duration:.2f}s")
        except Exception as tts_error:
            logger.error(f"[FLOW_PARAPHRASE_TTS_ERROR] Session: {session.session_id} | TTS failed: {str(tts_error)}")
        
        voice_input_action = "Use next_stage to learn new expressions and get next question"
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.PARAPHRASE,
            response_text=paraphrase_text,
            audio_url=audio_url,
            target_words=session.learned_expressions,
            completed=False,
            next_action=voice_input_action
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

async def _generate_openai_response_with_tts(session: ConversationSession, stage: ConversationStage, openai_service: OpenAIService, context: str = "") -> tuple[str, Optional[str]]:
    """OpenAI로 단계별 응답 생성"""
    
    try:
        # 언어 설정 - Mixed language 사용
        mixed_language = f"Mixed {session.from_lang}-{session.to_lang}"
        emotion_in_ai_lang = session.emotion if session.to_lang == "english" else session.emotion  # 영어 감정명 그대로 사용
        
        if stage == ConversationStage.STARTER:
            # 시작 단계: 감정 표현 학습 소개 + 질문
            prompt = f"""
            User selected {session.emotion} emotion.
            
            Create response in {mixed_language} (mixing Korean and English naturally):
            1. Introduce learning expressions related to "{emotion_in_ai_lang}" emotion in {session.to_lang}
            2. Ask engaging question like "~하면 {emotion_in_ai_lang}을 느끼게 되죠. 얘기해볼까요?" or "최근에 {emotion_in_ai_lang}을 느낀 적이 있나요?" in {session.from_lang}
            
            2-3 sentences, friendly casual tone. Mix languages naturally.   
            """
            
        elif stage == ConversationStage.FINISHER:
            # 완료 단계: 대화 마무리
            learned_words = [expr.word for expr in session.learned_expressions] if session.learned_expressions else []
            prompt = f"""
            Completed {session.user_input_count} conversations about {session.emotion} emotion.
            Learned expressions: {', '.join(learned_words) if learned_words else 'none'}
            
            Say goodbye in {mixed_language}: thanks + encouragement + mention learned expressions.
            2-3 sentences, friendly casual tone. Mix languages naturally.
            """
            
        elif stage == ConversationStage.RESTART:
            # 재시작 단계: 감정 표현 학습 소개 + 질문
            prompt = f"""
            Restarting conversation with {session.emotion} emotion.
            
            Create response in {mixed_language} (mixing Korean and English naturally):
            1. Introduce learning expressions related to "{emotion_in_ai_lang}" emotion in English
            2. Ask engaging question like "~하면 {emotion_in_ai_lang}을 느끼게 되죠. 얘기해볼까요?" or "최근에 {emotion_in_ai_lang}을 느낀 적이 있나요?"
            
            2-3 sentences, friendly casual tone. Mix languages naturally.
            """
            
        else:
            # 기타 단계의 경우 컨텍스트 사용
            prompt = f"""
            {session.emotion} emotion context: {context}
            
            Respond with empathy in {mixed_language}. 2-3 sentences, friendly casual tone. Mix languages naturally.
            """
        
        logger.info(f"[FLOW_OPENAI_STAGE_REQUEST] Session: {session.session_id} | Stage: {stage} | Generating response")
        
        response = await openai_service.get_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        
        generated_text = response.choices[0].message.content.strip()
        
        logger.info(f"[FLOW_OPENAI_STAGE_RESPONSE] Session: {session.session_id} | Stage: {stage} | Generated: {generated_text}")
        
        # TTS로 음성 변환 및 R2 업로드 (Mixed language이므로 Korean 기본 사용)
        audio_url = None
        try:
            # Mixed language이므로 Korean TTS 사용
            tts_language = "Korean"
            audio_url, duration = await openai_service.text_to_speech(generated_text, tts_language)
            logger.info(f"[FLOW_TTS_SUCCESS] Session: {session.session_id} | Stage: {stage} | Audio URL: {audio_url} | Duration: {duration:.2f}s")
        except Exception as tts_error:
            logger.error(f"[FLOW_TTS_ERROR] Session: {session.session_id} | Stage: {stage} | TTS failed: {str(tts_error)}")
            # TTS 실패해도 텍스트 응답은 반환
        
        return generated_text, audio_url
        
    except Exception as e:
        logger.error(f"[FLOW_OPENAI_STAGE_ERROR] Session: {session.session_id} | Stage: {stage} | Error: {str(e)}")
        
        # Emergency fallback - Mixed language 사용
        fallback_text = ""
        if stage == ConversationStage.STARTER:
            fallback_text = f"안녕하세요! {session.emotion} 감정과 관련된 expressions를 배워봐요. 최근에 {session.emotion}을 느낀 적이 있어요?"
        elif stage == ConversationStage.FINISHER:
            fallback_text = f"{session.emotion} 감정에 대해 이야기해주셔서 감사해요. 새로운 expressions를 잘 배우셨어요!"
        elif stage == ConversationStage.RESTART:
            fallback_text = f"새롭게 시작해봐요! {session.emotion}과 관련된 expressions를 배워볼까요?"
        else:
            fallback_text = f"{session.emotion} 감정을 이해해요. 더 이야기해주실 수 있어요?"
        
        # 폴백 응답에 대해서도 TTS 시도 (Mixed language이므로 Korean 기본 사용)
        audio_url = None
        try:
            fallback_tts_language = "English"  # Mixed language는 주로 영어 기반
            audio_url, duration = await openai_service.text_to_speech(fallback_text, fallback_tts_language)
            logger.info(f"[FLOW_TTS_FALLBACK_SUCCESS] Session: {session.session_id} | Stage: {stage} | Audio URL: {audio_url}")
        except Exception as tts_error:
            logger.error(f"[FLOW_TTS_FALLBACK_ERROR] Session: {session.session_id} | Stage: {stage} | TTS failed: {str(tts_error)}")
        
        return fallback_text, audio_url 