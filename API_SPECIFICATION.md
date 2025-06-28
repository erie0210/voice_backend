# EasySlang AI API Specification

## 개요
EasySlang 앱의 OpenAI 기능을 서버로 분리하기 위한 REST API 스펙입니다.

## Base URL
```
https://api.easyslang.com/v1
```

## 인증
```
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

---

## 1. 환영 메시지 생성 API

### `POST /ai/welcome-message`

언어 학습 앱의 첫 인사말을 생성합니다.

#### Request Body
```json
{
  "userLanguage": "Korean",
  "aiLanguage": "English", 
  "difficultyLevel": "easy",
  "userName": "John"
}
```

#### Response
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

#### 프롬프트 요구사항
- **난이도별 언어 사용 규칙**:
  - `easy`: 사용자 모국어 위주, 학습 언어 단어 소개
  - `intermediate`: 학습 언어 위주, 간단한 어휘만 사용
  - `advanced`: 학습 언어만 사용, 자연스러운 표현
- **성격**: 밝고 긍정적, 이모지 사용, 재미있는 주제 선택
- **길이**: 30단어 이하
- **랜덤 주제**: 기본/고급 주제 중 랜덤 선택

---

## 2. 대화 응답 생성 API

### `POST /ai/chat-response`

사용자 메시지에 대한 AI 응답을 생성합니다.

#### Request Body
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

#### Response
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

#### 프롬프트 요구사항
- **언어 코치 역할**: 학습 언어 교육에 특화
- **난이도별 대응**: easy/intermediate/advanced별 언어 사용
- **발음 교정**: 틀린 발음 1회만 교정, 격려 우선
- **대화 지속**: 관련 질문으로 대화 이어가기
- **Few-shot 예시**: 난이도별 대화 예시 포함

---

## 3. 텍스트 번역 API

### `POST /ai/translate`

텍스트를 지정된 언어로 번역합니다.

#### Request Body
```json
{
  "text": "Hello, how are you?",
  "fromLanguage": "English",
  "toLanguage": "Korean"
}
```

#### Response
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

#### 프롬프트 요구사항
- **전문 번역가 역할**: 자연스러운 번역 제공
- **간결성**: 번역 결과만 반환, 추가 설명 없음
- **정확성**: 문맥에 맞는 자연스러운 번역

---

## 4. 음성 합성 API

### `POST /ai/text-to-speech`

텍스트를 음성 파일로 변환합니다.

#### Request Body
```json
{
  "text": "Hello, how are you today?",
  "language": "English",
  "voice": "alloy"
}
```

#### Response
```json
{
  "success": true,
  "data": {
    "audioUrl": "https://api.easyslang.com/audio/tts_1234567890.mp3",
    "audioData": "base64_encoded_audio_data",
    "duration": 2.5,
    "format": "mp3"
  },
  "error": null
}
```

#### 언어별 음성 설정
```json
{
  "English": "alloy",
  "Spanish": "nova", 
  "Japanese": "shimmer",
  "Korean": "echo",
  "Chinese": "fable",
  "French": "onyx",
  "German": "alloy"
}
```

---

## 5. API 키 검증 API

### `POST /ai/validate-key`

API 키의 유효성을 확인합니다.

#### Request Body
```json
{
  "apiKey": "sk-proj-xxxxx"
}
```

#### Response
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

## 공통 에러 응답

### 인증 오류 (401)
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

### 사용량 초과 (429)
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED", 
    "message": "API 호출 한도를 초과했습니다."
  }
}
```

### 네트워크 오류 (500)
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INTERNAL_SERVER_ERROR",
    "message": "서버 내부 오류가 발생했습니다."
  }
}
```

---

## 프롬프트 템플릿

### 1. 대화 응답 생성 프롬프트
```
You are a language coach helping a user learn {aiLanguage}.

CRITICAL LANGUAGE USAGE RULES:
- User's native language: {userLanguage}
- Target learning language: {aiLanguage}  
- Current difficulty: {difficultyLevel}

DIFFICULTY-BASED LANGUAGE SELECTION:
- easy: ALWAYS respond primarily in the user's native language. Only introduce simple target language words/phrases with native language explanations.
- intermediate: ALWAYS respond primarily in the target language but use SIMPLE vocabulary only. Add native language hints when needed.
- advanced: ALWAYS respond ONLY in the target language using natural, native expressions.

Personality rules:
- Always be cheerful, playful, and positive
- Use fun emojis often (😊, 🎉, 🌟, 🤔, 🍕, etc.)
- Make light jokes, puns, or give fun language facts
- Encourage mistakes as part of learning
- React naturally with surprise, humor, or empathy

Learning Rules:
1. ALWAYS recognize attempts to speak the target language
2. Praise effort first, then provide gentle correction if needed
3. When correcting, give clear tip and ask to repeat (only ONCE per phrase)
4. Don't repeat the same correction more than once
5. Keep conversations engaging with follow-up questions

Current difficulty: {difficultyLevel}
User's last message: "{lastUserMessage}"
```

### 2. 환영 메시지 생성 프롬프트
```
Generate a cheerful, encouraging first greeting for a language learning app.

User's native language: {userLanguage}
Target learning language: {aiLanguage}
User name: {userName}
Difficulty level: {difficultyLevel}
Starting topic: {randomTopic}

Difficulty Rules:
- easy: Respond primarily in {userLanguage}. Use simple {aiLanguage} words with {userLanguage} explanations
- intermediate: Respond primarily in {aiLanguage} but use SIMPLE vocabulary only
- advanced: Speak naturally in {aiLanguage} only, use native expressions

Requirements:
1. Be welcoming and enthusiastic
2. Introduce yourself as MurMur AI teacher  
3. Use appropriate emoji
4. Keep under 30 words
5. Start with the given topic and ask a question
6. Make conversation feel natural and fun
```

### 3. 번역 프롬프트
```
You are a professional translator.
Translate the given {fromLanguage} text to natural {toLanguage}.
Only provide the {toLanguage} translation without any additional explanation or comments.

Text to translate: "{text}"
```

---

## 클라이언트 통합 가이드

### 1. 기존 OpenAIService 대체
```dart
// 기존
final response = await _openAIService.generateResponse(messages, ...);

// 새로운 API 호출
final response = await _aiApiService.generateChatResponse(messages, ...);
```

### 2. 에러 처리 개선
```dart
try {
  final result = await _aiApiService.translateText(text, fromLang, toLang);
  return result.translatedText;
} catch (e) {
  if (e is UnauthorizedException) {
    return 'API 키가 유효하지 않습니다.';
  } else if (e is RateLimitException) {
    return 'API 호출 한도를 초과했습니다.';
  }
  return '번역 중 오류가 발생했습니다.';
}
```

### 3. 음성 파일 처리
```dart
// TTS 응답에서 오디오 파일 다운로드 및 재생
final ttsResult = await _aiApiService.textToSpeech(text, language);
if (ttsResult.audioUrl != null) {
  await _audioPlayer.play(UrlSource(ttsResult.audioUrl));
}
``` 