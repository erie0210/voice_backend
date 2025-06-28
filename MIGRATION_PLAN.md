# OpenAI 기능 서버 분리 마이그레이션 계획

## 현재 OpenAI 사용 현황 분석

### 1. 사용 중인 메서드들
```dart
// lib/services/openai_service.dart
class OpenAIService {
  // 1. 환영 메시지 생성
  Future<String> generateWelcomeMessage({...}) async

  // 2. 대화 응답 생성  
  Future<String> generateResponse(List<ChatMessage> messages, {...}) async

  // 3. 텍스트 번역
  Future<String> translateText(String text, {...}) async

  // 4. 음성 합성 (TTS)
  Future<String?> speakText(String text, {...}) async

  // 5. 오디오 재생
  Future<void> playAudio(String path, {...}) async

  // 6. 음성 중지
  Future<void> stopSpeaking() async

  // 7. API 키 검증
  Future<bool> testApiKey() async
}
```

### 2. 호출 위치 분석
```dart
// lib/screens/chat_screen.dart에서 호출되는 메서드들:

// 환영 메시지 생성 (2곳)
- _generateWelcomeMessage() -> generateWelcomeMessage()
- _startActualChat() -> generateWelcomeMessage()

// 대화 응답 생성 (1곳)  
- _generateAIResponse() -> generateResponse()

// 텍스트 번역 (3곳)
- _addUserMessage() -> translateText() (사용자 메시지 번역)
- _generateAIResponse() -> translateText() (AI 응답 번역)  
- _startActualChat() -> translateText() (환영 메시지 번역)

// 음성 합성 (2곳)
- _generateAIResponse() -> speakText()
- _startActualChat() -> speakText()

// 음성 제어 (여러 곳)
- stopSpeaking() (8곳에서 호출)
- playAudio() (1곳에서 호출)
```

---

## 마이그레이션 단계별 계획

### Phase 1: 새로운 API 서비스 클래스 생성

#### 1.1 AI API 서비스 클래스 생성
```dart
// lib/services/ai_api_service.dart
class AiApiService {
  static const String baseUrl = 'https://api.easyslang.com/v1';
  
  Future<WelcomeMessageResponse> generateWelcomeMessage(WelcomeMessageRequest request);
  Future<ChatResponseResponse> generateChatResponse(ChatResponseRequest request);  
  Future<TranslateResponse> translateText(TranslateRequest request);
  Future<TextToSpeechResponse> textToSpeech(TextToSpeechRequest request);
  Future<ValidateKeyResponse> validateApiKey(String apiKey);
}
```

#### 1.2 응답 모델 클래스들 생성
```dart
// lib/models/api_responses.dart
class WelcomeMessageResponse {
  final bool success;
  final WelcomeMessageData? data;
  final ApiError? error;
}

class ChatResponseResponse {
  final bool success;
  final ChatResponseData? data;
  final ApiError? error;
}

// ... 기타 응답 모델들
```

### Phase 2: 기존 OpenAI 서비스 래핑

#### 2.1 하이브리드 서비스 생성
```dart
// lib/services/hybrid_ai_service.dart
class HybridAiService {
  final AiApiService _apiService;
  final OpenAIService _localService;
  final bool _useApiService;

  // API 우선, 실패시 로컬 OpenAI 서비스로 폴백
  Future<String> generateWelcomeMessage({...}) async {
    if (_useApiService) {
      try {
        final response = await _apiService.generateWelcomeMessage(...);
        return response.data?.message ?? _localService.generateWelcomeMessage(...);
      } catch (e) {
        return await _localService.generateWelcomeMessage(...);
      }
    }
    return await _localService.generateWelcomeMessage(...);
  }
}
```

### Phase 3: 점진적 마이그레이션

#### 3.1 기능별 순차 마이그레이션
1. **번역 기능** (가장 단순) → API 우선 적용
2. **환영 메시지 생성** → API 우선 적용  
3. **대화 응답 생성** (가장 복잡) → API 우선 적용
4. **음성 합성** (파일 처리 필요) → API 우선 적용

#### 3.2 설정으로 제어
```dart
// lib/config/app_config.dart
class AppConfig {
  static const bool useApiForTranslation = true;
  static const bool useApiForWelcomeMessage = true;
  static const bool useApiForChatResponse = false; // 아직 테스트 중
  static const bool useApiForTTS = false; // 아직 개발 중
}
```

### Phase 4: 완전 분리

#### 4.1 OpenAI 서비스 제거
- `openai_dart` 패키지 의존성 제거
- `lib/services/openai_service.dart` 삭제
- API 키 하드코딩 제거

#### 4.2 오디오 처리 로직 분리
```dart
// lib/services/audio_service.dart
class AudioService {
  Future<void> playFromUrl(String audioUrl);
  Future<void> playFromFile(String filePath);
  Future<void> stop();
}
```

---

## 서버 구현 요구사항

### 1. 기술 스택
- **Backend**: Node.js/Express 또는 Python/FastAPI
- **AI Provider**: OpenAI API
- **파일 저장**: AWS S3 또는 Google Cloud Storage  
- **캐싱**: Redis (번역 결과 캐싱)
- **모니터링**: 사용량 추적, 에러 로깅

### 2. 보안 요구사항
- API 키 관리 (환경 변수)
- 클라이언트 인증 (Bearer Token)
- Rate Limiting (사용자별/IP별)
- 입력 검증 및 Sanitization

### 3. 성능 요구사항
- 응답 시간: < 3초 (대화 생성)
- 응답 시간: < 1초 (번역)
- 응답 시간: < 5초 (TTS)
- 동시 접속: 100명 이상 지원

---

## 클라이언트 코드 변경사항

### 1. 의존성 변경
```yaml
# pubspec.yaml
dependencies:
  # 제거
  # openai_dart: ^0.5.2
  
  # 추가
  http: ^1.1.0
  dio: ^5.3.2 # HTTP 클라이언트
```

### 2. 서비스 교체
```dart
// lib/screens/chat_screen.dart
class _ChatScreenState extends State<ChatScreen> {
  // 기존
  // final OpenAIService _openAIService = OpenAIService();
  
  // 새로운
  final AiApiService _aiApiService = AiApiService();
  final AudioService _audioService = AudioService();
}
```

### 3. 메서드 호출 변경
```dart
// 기존
final response = await _openAIService.generateResponse(
  _messages,
  userLanguage: userLang,
  aiLanguage: aiLang,
  difficultyLevel: difficulty,
);

// 새로운
final request = ChatResponseRequest(
  messages: _messages.map((m) => ChatMessageDto.fromModel(m)).toList(),
  userLanguage: userLang,
  aiLanguage: aiLang,
  difficultyLevel: difficulty,
);
final response = await _aiApiService.generateChatResponse(request);
final responseText = response.data?.response ?? 'Error occurred';
```

---

## 테스트 계획

### 1. 단위 테스트
- API 서비스 메서드별 테스트
- 에러 처리 테스트
- 모델 직렬화/역직렬화 테스트

### 2. 통합 테스트  
- 실제 서버와의 연동 테스트
- 네트워크 오류 시나리오 테스트
- 폴백 메커니즘 테스트

### 3. 성능 테스트
- 응답 시간 측정
- 동시 요청 처리 테스트
- 메모리 사용량 모니터링

---

## 배포 전략

### 1. 단계적 배포
1. **Beta 테스트**: 내부 테스터 대상으로 API 기능 테스트
2. **Canary 배포**: 일부 사용자에게만 API 기능 활성화
3. **점진적 확대**: 성공률 모니터링하며 단계적 확대
4. **완전 전환**: 모든 사용자 API 기능으로 전환

### 2. 롤백 계획
- 서버 장애 시 즉시 로컬 OpenAI 서비스로 폴백
- 설정 플래그로 기능별 개별 롤백 가능
- 사용자 알림 없이 투명한 전환

### 3. 모니터링
- API 응답 시간 모니터링
- 에러율 추적
- 사용자 만족도 측정 (앱 평점, 피드백)

---

## 예상 이점

### 1. 보안 향상
- API 키 노출 위험 제거
- 서버 측 키 관리로 보안 강화

### 2. 성능 최적화
- 서버 측 캐싱으로 응답 속도 향상
- 프롬프트 최적화 용이

### 3. 비용 절감
- 중복 요청 캐싱으로 OpenAI API 호출 감소
- 사용량 모니터링 및 최적화 가능

### 4. 확장성
- 다른 AI 모델 쉽게 추가 가능
- A/B 테스트로 프롬프트 최적화
- 사용자별 개인화 기능 추가 가능

---

## 위험 요소 및 대응

### 1. 네트워크 의존성
- **위험**: 서버 장애 시 앱 기능 마비
- **대응**: 로컬 폴백 메커니즘 유지

### 2. 지연 시간 증가
- **위험**: 네트워크 레이턴시로 응답 지연
- **대응**: 캐싱, CDN 활용

### 3. 개발 복잡도 증가
- **위험**: 서버 개발 및 운영 복잡도
- **대응**: 단계적 마이그레이션, 충분한 테스트 