# Flow-Chat API 빠른 시작 가이드

## 🚀 5분 만에 시작하기

### 1. 기본 설정
```javascript
const API_BASE = 'http://localhost:8000/v1/ai';
let sessionId = null;
```

### 2. 감정 목록 가져오기
```javascript
const emotions = await fetch(`${API_BASE}/flow-chat/emotions`).then(r => r.json());
console.log(emotions.emotions); // ["happy", "sad", "angry", ...]
```

### 3. 대화 시작
```javascript
const response = await fetch(`${API_BASE}/flow-chat`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    action: 'pick_emotion',
    emotion: 'happy'
  })
});
const data = await response.json();
sessionId = data.session_id;
// 오디오 재생: data.audio_url
```

### 4. 단계별 진행
```javascript
// 다음 단계
const nextResponse = await fetch(`${API_BASE}/flow-chat`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: sessionId,
    action: 'next_stage'
  })
});

// 음성 입력
const voiceResponse = await fetch(`${API_BASE}/flow-chat`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: sessionId,
    action: 'voice_input',
    user_input: 'I got promoted today!'
  })
});
```

## 🎯 핵심 플로우

1. **pick_emotion** → 감정 선택, 세션 시작
2. **next_stage** → Starter → Prompt Cause 
3. **voice_input** → 사용자 답변 → Paraphrase
4. **next_stage** → Empathy & Vocabulary
5. **voice_input** → 발음 연습 → STT 피드백
6. **next_stage** → Finisher (완료)

## 🎵 오디오 처리

```javascript
// 사전 생성 음성 재생
if (data.audio_url) {
  new Audio(data.audio_url).play();
}

// 실시간 TTS (audio_url이 null인 경우)
if (!data.audio_url && data.response_text) {
  const utterance = new SpeechSynthesisUtterance(data.response_text);
  speechSynthesis.speak(utterance);
}
```

## 📊 응답 데이터 구조

```javascript
{
  "session_id": "uuid",
  "stage": "starter|prompt_cause|paraphrase|empathy_vocab|user_repeat|finisher",
  "response_text": "AI 응답 텍스트",
  "audio_url": "음성 파일 URL (선택적)",
  "target_words": ["학습할", "단어들"] (선택적),
  "stt_feedback": { "accuracy": 85.5, ... } (선택적),
  "completed": false,
  "next_action": "다음 액션 안내"
}
```

## 🎨 지원 감정 (12개)

```
happy, sad, angry, scared, shy, sleepy, 
upset, confused, bored, love, proud, nervous
```

각 감정마다 5개의 학습 단어가 제공됩니다.

## 🔧 유틸리티 함수

```javascript
// 세션 정보 조회
async function getSessionInfo(sessionId) {
  const response = await fetch(`${API_BASE}/flow-chat/session/${sessionId}`);
  return await response.json();
}

// 세션 삭제
async function deleteSession(sessionId) {
  await fetch(`${API_BASE}/flow-chat/session/${sessionId}`, {
    method: 'DELETE'
  });
}

// 대화 재시작
async function restartConversation(sessionId) {
  const response = await fetch(`${API_BASE}/flow-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      action: 'restart'
    })
  });
  return await response.json();
}
```

## 🚨 에러 처리

```javascript
try {
  const response = await fetch(`${API_BASE}/flow-chat`, { ... });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = await response.json();
} catch (error) {
  console.error('API 에러:', error.message);
}
```

## 📱 모바일 구현 팁

1. **오디오 캐싱**: 사전 생성 음성 파일을 로컬에 저장
2. **STT 권한**: 마이크 권한 요청 처리
3. **네트워크 체크**: 오프라인 상태 감지
4. **진행 상태 저장**: 앱 종료 시 세션 ID 저장

## 🎯 완전한 예시

```javascript
class FlowChatManager {
  constructor() {
    this.baseURL = 'http://localhost:8000/v1/ai';
    this.sessionId = null;
  }

  async startConversation(emotion) {
    const response = await fetch(`${this.baseURL}/flow-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'pick_emotion', emotion })
    });
    const data = await response.json();
    this.sessionId = data.session_id;
    return data;
  }

  async nextStage() {
    return await this.makeRequest('next_stage');
  }

  async sendVoiceInput(userInput) {
    return await this.makeRequest('voice_input', { user_input: userInput });
  }

  async makeRequest(action, extra = {}) {
    const response = await fetch(`${this.baseURL}/flow-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        action,
        ...extra
      })
    });
    return await response.json();
  }
}

// 사용법
const flowChat = new FlowChatManager();
const startData = await flowChat.startConversation('happy');
const nextData = await flowChat.nextStage();
const voiceData = await flowChat.sendVoiceInput('I got promoted!');
```

이 가이드로 Flow-Chat API를 쉽게 시작할 수 있습니다! 🚀 