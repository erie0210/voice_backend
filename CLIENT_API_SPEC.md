# EasySlang AI API 클라이언트 통합 가이드

## 1. 인증

- 모든 요청은 `Authorization: Bearer <API_SECRET_KEY>` 헤더가 필요합니다.
- 테스트용 기본값:  
  `Authorization: Bearer easyslang-api-secret-key-2024`

---

## 2. Base URL

- 로컬 개발:  
  `http://localhost:8000/v1/ai`
- 운영 배포 시 별도 안내

---

## 3. 엔드포인트별 상세

### 3.1. 환영 메시지 생성

- **POST** `/v1/ai/welcome-message`
- **설명:** 언어 학습 앱의 첫 인사말을 생성합니다.

#### 요청 예시
```json
{
  "userLanguage": "Korean",
  "aiLanguage": "English",
  "difficultyLevel": "easy",
  "userName": "John"
}
```

#### 응답 예시
```json
{
  "success": true,
  "data": {
    "message": "안녕하세요 John! 😊 저는 MurMur입니다. 오늘은 취미에 대해 이야기해볼까요? 당신의 취미는 무엇인가요?",
    "fallbackMessage": "Hello John! 😊 I'm MurMur. Let's talk about hobbies today!"
  },
  "error": null
}
```

---

### 3.2. 대화 응답 생성

- **POST** `/v1/ai/chat-response`
- **설명:** 사용자 메시지에 대한 AI 응답을 생성합니다.

#### 요청 예시
```json
{
  "messages": [
    {
      "role": "user",
      "content": "I like music",
      "isUser": true,
      "timestamp": "2024-01-01T00:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Great! What kind of music do you like?",
      "isUser": false,
      "timestamp": "2024-01-01T00:00:01Z"
    }
  ],
  "userLanguage": "Korean",
  "aiLanguage": "English",
  "difficultyLevel": "intermediate",
  "lastUserMessage": "I like pop music"
}
```

#### 응답 예시
```json
{
  "success": true,
  "data": {
    "response": "Awesome! Pop music is really popular! 🎵 Do you have a favorite pop artist? «인기 있는 팝 가수가 있나요?»",
    "practiceExpression": null
  },
  "error": null
}
```

---

### 3.3. 텍스트 번역

- **POST** `/v1/ai/translate`
- **설명:** 텍스트를 지정된 언어로 번역합니다.

#### 요청 예시
```json
{
  "text": "Hello, how are you?",
  "fromLanguage": "English",
  "toLanguage": "Korean"
}
```

#### 응답 예시
```json
{
  "success": true,
  "data": {
    "translatedText": "안녕하세요, 어떻게 지내세요?",
    "originalText": "Hello, how are you?",
    "fromLanguage": "English",
    "toLanguage": "Korean"
  },
  "error": null
}
```

---

### 3.4. 음성 합성 (TTS)

- **POST** `/v1/ai/text-to-speech`
- **설명:** 텍스트를 음성(mp3) 파일로 변환합니다.

#### 요청 예시
```json
{
  "text": "Hello, how are you today?",
  "language": "English",
  "voice": "alloy"
}
```
- `voice`는 생략 가능, 언어별 기본값 자동 적용

#### 응답 예시
```json
{
  "success": true,
  "data": {
    "audioUrl": "/audio/tts_1234567890.mp3",
    "audioData": null,
    "duration": 2.5,
    "format": "mp3"
  },
  "error": null
}
```
- **audioUrl**: 서버에서 정적 파일로 서빙됨.  
  예시: `http://localhost:8000/audio/tts_1234567890.mp3`
- 클라이언트는 이 URL을 `<audio>` 태그, 오디오 플레이어 등에서 바로 재생 가능

---

### 3.5. API 키 검증

- **POST** `/v1/ai/validate-key`
- **설명:** OpenAI API 키의 유효성을 확인합니다.

#### 요청 예시
```json
{
  "apiKey": "sk-proj-xxxxx"
}
```

#### 응답 예시
```json
{
  "success": true,
  "data": {
    "isValid": true,
    "usage": {
      "totalTokens": 1500,
      "remainingTokens": 8500
    }
  },
  "error": null
}
```

---

## 4. 공통 에러 응답

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "API 키가 유효하지 않습니다."
  }
}
```
- 인증 실패, 사용량 초과, 서버 오류 등은 `success: false`와 함께 `error` 필드에 상세 정보 제공

---

## 5. 기타 참고사항

- 모든 요청/응답은 `application/json` 형식
- 시간 필드는 ISO 8601 포맷 사용 (`2024-01-01T00:00:00Z`)
- 음성 파일은 서버에서 정적 파일로 서빙되므로, URL로 바로 접근/재생 가능
- 실제 배포 시에는 HTTPS, 도메인, 인증키 등 별도 안내 예정

---

**문의 및 피드백:**  
담당자에게 문의하거나, API 문서에 대한 개선 요청은 언제든 환영합니다! 