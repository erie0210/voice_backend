from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
import json
from datetime import datetime

from services.openai_service import OpenAIService
from models.api_models import LanguageCode

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

def get_openai_service():
    return OpenAIService()

@router.post("/flow-chat", response_model=FlowChatResponse)
async def flow_chat(
    request: FlowChatRequest,
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
    
    try:
        # 새 세션 생성 또는 기존 세션 로드
        if request.action == FlowAction.PICK_EMOTION:
            if not request.emotion:
                raise HTTPException(status_code=400, detail="Emotion is required for pick_emotion action")
            
            session_id = str(uuid.uuid4())
            session = ConversationSession(
                session_id=session_id,
                emotion=request.emotion.lower(),
                from_lang=request.from_lang.value,
                to_lang=request.to_lang.value
            )
            sessions[session_id] = session
            
            # 첫 번째 단계: Starter
            response_text = STAGE_RESPONSES[ConversationStage.STARTER].get(
                request.emotion.lower(), 
                f"Hello! I can see you're feeling {request.emotion}. Let's talk about it!"
            )
            
            return FlowChatResponse(
                session_id=session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=f"https://voice.kreators.dev/flow_conversations/{request.emotion.lower()}/starter.mp3",
                completed=False,
                next_action="Listen to the audio and proceed to next stage"
            )
        
        # 기존 세션 처리
        if not request.session_id or request.session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = sessions[request.session_id]
        session.updated_at = datetime.now()
        
        if request.action == FlowAction.NEXT_STAGE:
            return await _handle_next_stage(session, openai_service)
        
        elif request.action == FlowAction.VOICE_INPUT:
            if not request.user_input:
                raise HTTPException(status_code=400, detail="User input is required for voice_input action")
            
            return await _handle_voice_input(session, request.user_input, openai_service)
        
        elif request.action == FlowAction.RESTART:
            session.stage = ConversationStage.STARTER
            session.user_answers = []
            session.learned_words = []
            
            response_text = STAGE_RESPONSES[ConversationStage.STARTER][session.emotion]
            
            return FlowChatResponse(
                session_id=session.session_id,
                stage=ConversationStage.STARTER,
                response_text=response_text,
                audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/starter.mp3",
                completed=False,
                next_action="Listen to the audio and proceed to next stage"
            )
        
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def _handle_next_stage(session: ConversationSession, openai_service: OpenAIService) -> FlowChatResponse:
    """다음 단계로 진행"""
    
    if session.stage == ConversationStage.STARTER:
        # Stage 2: Prompt cause
        session.stage = ConversationStage.PROMPT_CAUSE
        response_text = STAGE_RESPONSES[ConversationStage.PROMPT_CAUSE][session.emotion]
        
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
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.FINISHER,
            response_text=response_text,
            audio_url=f"https://voice.kreators.dev/flow_conversations/{session.emotion}/finisher.mp3",
            completed=True,
            next_action="Conversation completed! Your learned words have been saved."
        )
    
    else:
        raise HTTPException(status_code=400, detail="Cannot proceed to next stage from current stage")

async def _handle_voice_input(session: ConversationSession, user_input: str, openai_service: OpenAIService) -> FlowChatResponse:
    """음성 입력 처리"""
    
    if session.stage == ConversationStage.PROMPT_CAUSE:
        # Stage 3: User answer -> Stage 4: Paraphrase
        session.stage = ConversationStage.USER_ANSWER
        session.user_answers.append(user_input)
        
        # OpenAI로 사용자 답변 패러프레이징
        paraphrase_prompt = f"User said: '{user_input}' about feeling {session.emotion}. Please paraphrase this in a supportive way and highlight key emotional words."
        
        try:
            paraphrase_response = await openai_service.get_chat_completion(
                messages=[{"role": "user", "content": paraphrase_prompt}],
                temperature=0.7
            )
            response_text = paraphrase_response.choices[0].message.content
        except Exception:
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
        
        return FlowChatResponse(
            session_id=session.session_id,
            stage=ConversationStage.USER_REPEAT,
            response_text=response_text,
            stt_feedback=stt_feedback,
            completed=False,
            next_action="Proceed to finish the conversation"
        )
    
    else:
        raise HTTPException(status_code=400, detail="Voice input not expected at current stage")

@router.get("/flow-chat/session/{session_id}")
async def get_session_info(session_id: str):
    """세션 정보 조회"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return {
        "session_id": session.session_id,
        "emotion": session.emotion,
        "stage": session.stage,
        "learned_words": session.learned_words,
        "user_answers": session.user_answers,
        "created_at": session.created_at,
        "updated_at": session.updated_at
    }

@router.delete("/flow-chat/session/{session_id}")
async def delete_session(session_id: str):
    """세션 삭제"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del sessions[session_id]
    return {"message": "Session deleted successfully"}

@router.get("/flow-chat/emotions")
async def get_available_emotions():
    """사용 가능한 감정 목록 조회"""
    return {
        "emotions": list(EMOTION_VOCABULARY.keys()),
        "vocabulary_preview": {
            emotion: words[:2] for emotion, words in EMOTION_VOCABULARY.items()
        }
    } 