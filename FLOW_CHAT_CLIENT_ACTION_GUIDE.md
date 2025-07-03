# Flow-Chat API 클라이언트 액션 가이드

## 🎯 개요
Flow-Chat API에서 클라이언트가 보내는 액션(`next_stage` vs `voice_input`)의 명확한 사용 규칙을 정의합니다.

## 📋 액션 타입 정의

### 1. `next_stage` 액션
- **사용 시점**: AI가 음성/텍스트를 제공한 후, 사용자가 **듣기만 하고** 다음 단계로 진행할 때
- **특징**: 사용자 입력이 필요 없는 단계 전환
- **`user_input` 필드**: `null` 또는 생략

### 2. `voice_input` 액션  
- **사용 시점**: AI가 질문하거나 발음 연습을 요청한 후, 사용자가 **음성으로 응답**할 때
- **특징**: 사용자의 음성 입력이 필요한 상호작용
- **`user_input` 필드**: 필수 (STT 결과)

## 🔄 단계별 액션 매트릭스

| 현재 단계 | 단계 설명 | 클라이언트 액션 | 사용자 행동 | 다음 단계 |
|-----------|-----------|-----------------|-------------|-----------|
| `starter` | AI 인사말 제공 | `next_stage` | 오디오 듣기 | `prompt_cause` |
| `prompt_cause` | AI 감정 원인 질문 | `voice_input` | 음성으로 답변 | `paraphrase` |
| `paraphrase` | AI 답변 패러프레이징 | `next_stage` | 텍스트 읽기/듣기 | `empathy_vocab` |
| `empathy_vocab` | AI 새 단어 가르치기 | `voice_input` | 단어 발음 연습 | `user_repeat` |
| `user_repeat` | AI 발음 체크 완료 | `next_stage` | 결과 확인 | `finisher` |
| `finisher` | AI 대화 마무리 | - | 대화 완료 | - |

## 🎵 액션 선택 가이드

### 📢 `next_stage`를 사용하는 경우

#### 1. **오디오 재생 완료 후**
```javascript
// AI가 사전 생성된 오디오 제공 → 사용자가 듣기 완료
{
  "session_id": "xxx",
  "action": "next_stage"
}
```

**해당 단계:**
- `starter` → `prompt_cause` (인사말 듣기 완료)
- `paraphrase` → `empathy_vocab` (패러프레이징 듣기 완료)  
- `user_repeat` → `finisher` (발음 체크 결과 확인 완료)

#### 2. **텍스트 읽기 완료 후**
```javascript
// AI가 실시간 텍스트 제공 → 사용자가 읽기 완료
{
  "session_id": "xxx", 
  "action": "next_stage"
}
```

### 🎤 `voice_input`을 사용하는 경우

#### 1. **AI 질문에 답변할 때**
```javascript
// AI가 감정 원인 질문 → 사용자가 음성으로 답변
{
  "session_id": "xxx",
  "action": "voice_input",
  "user_input": "I got promoted at work today!"
}
```

**해당 단계:**
- `prompt_cause` → `paraphrase` (감정 원인 답변)

#### 2. **발음 연습할 때**
```javascript
// AI가 새 단어 가르치기 → 사용자가 발음 연습
{
  "session_id": "xxx",
  "action": "voice_input", 
  "user_input": "joyful delighted cheerful"
}
```

**해당 단계:**
- `empathy_vocab` → `user_repeat` (새 단어 발음 연습)

## 🚨 잘못된 액션 사용 시 처리

### 1. **`next_stage`를 잘못 보낸 경우**
```javascript
// empathy_vocab 단계에서 next_stage 보낸 경우
{
  "session_id": "xxx",
  "stage": "empathy_vocab",
  "response_text": "Great! Now it's time to practice pronunciation. Please say these words: joyful, delighted, cheerful",
  "next_action": "Please use voice input to practice pronunciation"
}
```

### 2. **`voice_input`을 잘못 보낸 경우**
```javascript
// HTTP 400 에러 반환
{
  "detail": "Voice input not expected at current stage"
}
```

## 📱 클라이언트 구현 예시

### React/JavaScript 구현
```javascript
class FlowChatClient {
  async handleStageTransition(currentStage, hasAudio) {
    // 오디오가 있는 경우 재생 완료 후 next_stage
    if (hasAudio) {
      await this.playAudio(audioUrl);
      return this.sendAction('next_stage');
    }
    
    // 텍스트만 있는 경우 사용자 확인 후 next_stage  
    return this.sendAction('next_stage');
  }

  async handleVoiceInput(sttResult) {
    // 음성 인식 결과를 voice_input으로 전송
    return this.sendAction('voice_input', sttResult);
  }

  sendAction(action, userInput = null) {
    return fetch('/v1/ai/flow-chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: this.sessionId,
        action: action,
        user_input: userInput
      })
    });
  }
}
```

### Flutter/Dart 구현
```dart
class FlowChatService {
  Future<Map<String, dynamic>> nextStage() async {
    return await _sendRequest({
      'session_id': sessionId,
      'action': 'next_stage'
    });
  }

  Future<Map<String, dynamic>> sendVoiceInput(String sttResult) async {
    return await _sendRequest({
      'session_id': sessionId,
      'action': 'voice_input',
      'user_input': sttResult
    });
  }
}
```

## 📊 응답의 `next_action` 필드 활용

서버 응답의 `next_action` 필드를 통해 클라이언트가 다음에 어떤 액션을 보내야 하는지 확인할 수 있습니다.

```javascript
{
  "next_action": "Listen to the audio and proceed to next stage"
  // → next_stage 액션 준비
}

{
  "next_action": "Please answer the question using voice input"  
  // → voice_input 액션 준비
}

{
  "next_action": "Please use voice input to practice pronunciation"
  // → voice_input 액션 준비  
}
```

## 🔍 디버깅 팁

### 1. **로그 확인**
```
[FLOW_API_REQUEST] IP: xxx | Request: {'action': 'next_stage', 'session_id': 'xxx'}
[FLOW_SESSION_ACTIVITY] {'activity': 'SESSION_ACCESSED', 'current_stage': 'empathy_vocab'}
[FLOW_STAGE_TRANSITION] Session: xxx | From: empathy_vocab | Emotion: happy
```

### 2. **세션 상태 확인**
```javascript
GET /v1/ai/flow-chat/session/{session_id}
```

### 3. **단계별 체크리스트**
- [ ] 현재 단계가 올바른가?
- [ ] 오디오 재생이 완료되었는가?
- [ ] 사용자 음성 입력이 필요한 단계인가?
- [ ] STT 결과가 올바르게 전달되었는가?

## 📝 요약

| 상황 | 액션 | 예시 |
|------|------|------|
| 오디오 듣기 완료 | `next_stage` | 인사말, 단어 설명 듣기 후 |
| 텍스트 읽기 완료 | `next_stage` | 패러프레이징 읽기 후 |
| 질문에 답변 | `voice_input` | 감정 원인 질문 답변 |
| 발음 연습 | `voice_input` | 새 단어 발음 연습 |

이 가이드를 따르면 Flow-Chat API와 올바르게 상호작용할 수 있습니다. 