# Flow-Chat API 완전 가이드

## 🎯 개요
Flow-Chat은 7단계 감정 기반 언어학습 대화 시스템입니다. 사용자가 감정을 선택하고 7턴의 대화를 통해 최소 5개의 감정 관련 영어 단어를 학습할 수 있습니다.

## 📋 API 기본 정보

**Base URL:** `http://localhost:8000/v1/ai`

**Content-Type:** `application/json`

**주요 엔드포인트:**
- `POST /flow-chat` - 메인 대화 처리
- `GET /flow-chat/session/{session_id}` - 세션 정보 조회
- `DELETE /flow-chat/session/{session_id}` - 세션 삭제
- `GET /flow-chat/emotions` - 사용 가능한 감정 목록

## 🔄 7단계 학습 플로우

### Stage 0: 감정 선택 (UI)
사용자가 12개 감정 중 하나를 선택합니다.

### Stage 1: Starter (사전 생성 음성)
AI가 선택된 감정에 맞는 인사말을 제공합니다.

### Stage 2: Prompt Cause (사전 생성 음성)
AI가 감정의 원인에 대해 질문합니다.

### Stage 3: User Answer (STT)
사용자가 음성으로 답변합니다.

### Stage 4: Paraphrase (실시간 TTS)
AI가 사용자 답변을 패러프레이징하고 공감합니다.

### Stage 5: Empathy & Vocabulary (사전 생성 음성)
AI가 공감을 표현하고 새로운 어휘 3개를 가르칩니다.

### Stage 6: User Repeat (발음 체크)
사용자가 새 단어들을 발음하고 정확도를 측정합니다.

### Stage 7: Finisher (사전 생성 음성)
AI가 대화를 마무리하고 학습 완료를 축하합니다.

## 🎨 지원 감정 및 학습 단어

```javascript
const EMOTIONS = {
  happy: ["joyful", "delighted", "cheerful", "content", "pleased"],
  sad: ["sorrowful", "melancholy", "disappointed", "heartbroken", "gloomy"],
  angry: ["furious", "irritated", "annoyed", "outraged", "frustrated"],
  scared: ["terrified", "anxious", "worried", "nervous", "frightened"],
  shy: ["bashful", "timid", "reserved", "modest", "self-conscious"],
  sleepy: ["drowsy", "tired", "exhausted", "weary", "fatigued"],
  upset: ["distressed", "troubled", "bothered", "agitated", "disturbed"],
  confused: ["puzzled", "bewildered", "perplexed", "uncertain", "lost"],
  bored: ["uninterested", "restless", "weary", "disengaged", "listless"],
  love: ["affectionate", "devoted", "caring", "passionate", "tender"],
  proud: ["accomplished", "satisfied", "confident", "triumphant", "honored"],
  nervous: ["anxious", "tense", "uneasy", "jittery", "apprehensive"]
};
```

## 📡 API 스펙

### 1. 감정 선택 및 세션 시작

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "action": "pick_emotion",
  "emotion": "happy",
  "from_lang": "KOREAN",
  "to_lang": "ENGLISH"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "starter",
  "response_text": "Hi there! I can see you're feeling happy today. That's wonderful! 😊",
  "audio_url": "https://voice.kreators.dev/flow_conversations/happy/starter.mp3",
  "completed": false,
  "next_action": "Listen to the audio and proceed to next stage"
}
```

### 2. 다음 단계 진행

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "next_stage"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "prompt_cause",
  "response_text": "What made you feel so happy today? Tell me about it!",
  "audio_url": "https://voice.kreators.dev/flow_conversations/happy/prompt_cause.mp3",
  "completed": false,
  "next_action": "Please answer the question using voice input"
}
```

### 3. 음성 입력 처리

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "voice_input",
  "user_input": "I got promoted at work today!"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "paraphrase",
  "response_text": "That's wonderful! Getting promoted is such an achievement...",
  "audio_url": null,
  "completed": false,
  "next_action": "Proceed to learn new vocabulary"
}
```

### 4. 어휘 학습 단계

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "next_stage"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "empathy_vocab",
  "response_text": "I understand how you feel. Let me teach you some new words to express happy: joyful, delighted, cheerful",
  "audio_url": "https://voice.kreators.dev/flow_conversations/happy/empathy_vocab.mp3",
  "target_words": ["joyful", "delighted", "cheerful"],
  "completed": false,
  "next_action": "Listen to the new vocabulary and try to repeat"
}
```

### 5. 발음 연습 및 체크

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "voice_input",
  "user_input": "joyful delighted cheerful"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "user_repeat",
  "response_text": "Good effort! You pronounced 3 out of 3 words correctly.",
  "stt_feedback": {
    "accuracy": 100.0,
    "recognized_words": ["joyful", "delighted", "cheerful"],
    "total_words": 3,
    "feedback": "Great job!"
  },
  "completed": false,
  "next_action": "Proceed to finish the conversation"
}
```

### 6. 대화 완료

**요청:**
```javascript
POST /v1/ai/flow-chat
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "next_stage"
}
```

**응답:**
```javascript
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "finisher",
  "response_text": "I'm so glad we talked about your happiness! Keep spreading those positive vibes! ✨",
  "audio_url": "https://voice.kreators.dev/flow_conversations/happy/finisher.mp3",
  "completed": true,
  "next_action": "Conversation completed! Your learned words have been saved."
}
```

## 🔧 보조 API

### 세션 정보 조회
```javascript
GET /v1/ai/flow-chat/session/{session_id}

// 응답
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "emotion": "happy",
  "stage": "finisher",
  "learned_words": ["joyful", "delighted", "cheerful"],
  "user_answers": ["I got promoted at work today!"],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:35:00Z"
}
```

### 사용 가능한 감정 목록
```javascript
GET /v1/ai/flow-chat/emotions

// 응답
{
  "emotions": ["happy", "sad", "angry", "scared", "shy", "sleepy", "upset", "confused", "bored", "love", "proud", "nervous"],
  "vocabulary_preview": {
    "happy": ["joyful", "delighted"],
    "sad": ["sorrowful", "melancholy"]
  }
}
```

### 세션 삭제
```javascript
DELETE /v1/ai/flow-chat/session/{session_id}

// 응답
{
  "message": "Session deleted successfully"
}
```

## 💻 클라이언트 구현 예시

### React/JavaScript 예시

```javascript
class FlowChatClient {
  constructor(baseURL = 'http://localhost:8000/v1/ai') {
    this.baseURL = baseURL;
    this.sessionId = null;
    this.currentStage = null;
  }

  async startConversation(emotion, fromLang = 'KOREAN', toLang = 'ENGLISH') {
    const response = await fetch(`${this.baseURL}/flow-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'pick_emotion',
        emotion: emotion,
        from_lang: fromLang,
        to_lang: toLang
      })
    });
    
    const data = await response.json();
    this.sessionId = data.session_id;
    this.currentStage = data.stage;
    return data;
  }

  async nextStage() {
    const response = await fetch(`${this.baseURL}/flow-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        action: 'next_stage'
      })
    });
    
    const data = await response.json();
    this.currentStage = data.stage;
    return data;
  }

  async sendVoiceInput(userInput) {
    const response = await fetch(`${this.baseURL}/flow-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        action: 'voice_input',
        user_input: userInput
      })
    });
    
    const data = await response.json();
    this.currentStage = data.stage;
    return data;
  }

  async getSessionInfo() {
    const response = await fetch(`${this.baseURL}/flow-chat/session/${this.sessionId}`);
    return await response.json();
  }

  async getAvailableEmotions() {
    const response = await fetch(`${this.baseURL}/flow-chat/emotions`);
    return await response.json();
  }
}

// 사용 예시
const client = new FlowChatClient();

// 1. 대화 시작
const startResponse = await client.startConversation('happy');
console.log(startResponse.response_text);
// 오디오 재생: startResponse.audio_url

// 2. 다음 단계
const promptResponse = await client.nextStage();
console.log(promptResponse.response_text);
// 오디오 재생: promptResponse.audio_url

// 3. 사용자 답변
const answerResponse = await client.sendVoiceInput("I got promoted today!");
console.log(answerResponse.response_text);

// 4. 어휘 학습
const vocabResponse = await client.nextStage();
console.log(vocabResponse.target_words); // ["joyful", "delighted", "cheerful"]

// 5. 발음 체크
const pronunciationResponse = await client.sendVoiceInput("joyful delighted cheerful");
console.log(pronunciationResponse.stt_feedback);

// 6. 대화 완료
const finishResponse = await client.nextStage();
console.log(finishResponse.response_text);
console.log(finishResponse.completed); // true
```

## 📱 모바일 앱 플로우 예시

### Flutter/Dart 예시

```dart
class FlowChatService {
  final String baseUrl = 'http://localhost:8000/v1/ai';
  String? sessionId;
  String? currentStage;

  Future<Map<String, dynamic>> startConversation(String emotion) async {
    final response = await http.post(
      Uri.parse('$baseUrl/flow-chat'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'action': 'pick_emotion',
        'emotion': emotion,
        'from_lang': 'KOREAN',
        'to_lang': 'ENGLISH'
      }),
    );

    final data = jsonDecode(response.body);
    sessionId = data['session_id'];
    currentStage = data['stage'];
    return data;
  }

  Future<Map<String, dynamic>> nextStage() async {
    final response = await http.post(
      Uri.parse('$baseUrl/flow-chat'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'session_id': sessionId,
        'action': 'next_stage'
      }),
    );

    final data = jsonDecode(response.body);
    currentStage = data['stage'];
    return data;
  }

  Future<Map<String, dynamic>> sendVoiceInput(String userInput) async {
    final response = await http.post(
      Uri.parse('$baseUrl/flow-chat'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'session_id': sessionId,
        'action': 'voice_input',
        'user_input': userInput
      }),
    );

    final data = jsonDecode(response.body);
    currentStage = data['stage'];
    return data;
  }
}
```

## 🎵 오디오 처리 가이드

### 오디오 파일 재생
```javascript
// 사전 생성 음성 파일 재생
function playAudio(audioUrl) {
  if (audioUrl) {
    const audio = new Audio(audioUrl);
    audio.play();
  }
}

// 실시간 TTS (audio_url이 null인 경우)
function speakText(text) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'en-US';
  speechSynthesis.speak(utterance);
}
```

### STT (Speech-to-Text) 처리
```javascript
// Web Speech API 사용 예시
function startSpeechRecognition() {
  const recognition = new webkitSpeechRecognition();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = function(event) {
    const transcript = event.results[0][0].transcript;
    // transcript를 API로 전송
    client.sendVoiceInput(transcript);
  };

  recognition.start();
}
```

## 🚨 에러 처리

### 일반적인 에러 응답
```javascript
{
  "detail": "Session not found" // 404
}
{
  "detail": "Emotion is required for pick_emotion action" // 400
}
{
  "detail": "Internal server error: ..." // 500
}
```

### 에러 처리 예시
```javascript
try {
  const response = await client.startConversation('happy');
  // 성공 처리
} catch (error) {
  if (error.status === 404) {
    console.error('세션을 찾을 수 없습니다.');
  } else if (error.status === 400) {
    console.error('잘못된 요청입니다.');
  } else {
    console.error('서버 오류가 발생했습니다.');
  }
}
```

## 🔍 디버깅 및 테스트

### cURL 테스트 명령어
```bash
# 1. 감정 목록 조회
curl -X GET "http://localhost:8000/v1/ai/flow-chat/emotions"

# 2. 대화 시작
curl -X POST "http://localhost:8000/v1/ai/flow-chat" \
  -H "Content-Type: application/json" \
  -d '{"action": "pick_emotion", "emotion": "happy"}'

# 3. 세션 정보 확인
curl -X GET "http://localhost:8000/v1/ai/flow-chat/session/YOUR_SESSION_ID"
```

### 로그 확인
서버 로그에서 다음 정보를 확인할 수 있습니다:
- 세션 생성/업데이트
- OpenAI API 호출
- 음성 파일 URL 생성
- 발음 정확도 계산

## 🎯 베스트 프랙티스

1. **세션 관리**: 세션 ID를 안전하게 저장하고 관리하세요.
2. **오디오 캐싱**: 사전 생성된 음성 파일을 로컬에 캐싱하여 성능을 향상시키세요.
3. **오프라인 처리**: 네트워크 오류 시 적절한 폴백 메시지를 제공하세요.
4. **진행 상태 저장**: 사용자가 앱을 종료해도 학습 진행 상태를 복원할 수 있도록 하세요.
5. **발음 피드백**: STT 정확도를 시각적으로 표시하여 사용자 경험을 향상시키세요.

이 가이드를 참고하여 Flow-Chat API를 활용한 언어학습 앱을 구현해보세요! 🚀 