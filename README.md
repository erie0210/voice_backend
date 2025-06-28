# EasySlang AI API Server

OpenAI 기반 언어 학습 API 서버입니다. FastAPI로 구현되었으며 Railway에 배포 가능합니다.

## 기능

- 🔄 **텍스트 번역**: OpenAI를 사용한 자연스러운 번역
- 🔐 **API 인증**: Bearer 토큰 기반 보안
- 📊 **헬스 체크**: 서버 상태 모니터링
- 🚀 **Railway 배포**: 원클릭 배포 지원

## 로컬 개발 환경 설정

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 확인하고 필요시 수정:

```bash
OPENAI_API_KEY=your_openai_api_key_here
API_SECRET_KEY=your_api_secret_key_here
```

### 3. 서버 실행

```bash
# 개발 모드
uvicorn main:app --reload

# 프로덕션 모드
python main.py
```

서버는 `http://localhost:8000`에서 실행됩니다.

## API 사용법

### 인증

모든 API 요청에는 Authorization 헤더가 필요합니다:

```
Authorization: Bearer easyslang-api-secret-key-2024
```

### 번역 API

**POST** `/v1/ai/translate`

```json
{
  "text": "Hello, how are you?",
  "fromLanguage": "English",
  "toLanguage": "Korean"
}
```

**응답:**

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

### API 키 검증

**POST** `/v1/ai/validate-key`

OpenAI API 키의 유효성을 확인합니다.

## Railway 배포

### 1. Railway 계정 생성

[Railway](https://railway.app) 계정을 생성합니다.

### 2. 프로젝트 연결

```bash
# Railway CLI 설치
npm install -g @railway/cli

# 로그인
railway login

# 프로젝트 초기화
railway init

# 배포
railway up
```

### 3. 환경 변수 설정

Railway 대시보드에서 다음 환경 변수를 설정합니다:

- `OPENAI_API_KEY`: OpenAI API 키
- `API_SECRET_KEY`: API 인증 키

### 4. 도메인 확인

배포 완료 후 Railway에서 제공하는 도메인으로 API에 접근할 수 있습니다.

## API 문서

서버 실행 후 다음 URL에서 자동 생성된 API 문서를 확인할 수 있습니다:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 테스트

### cURL로 번역 테스트

```bash
curl -X POST "http://localhost:8000/v1/ai/translate" \
  -H "Authorization: Bearer easyslang-api-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, how are you today?",
    "fromLanguage": "English", 
    "toLanguage": "Korean"
  }'
```

### Python으로 테스트

```python
import requests

url = "http://localhost:8000/v1/ai/translate"
headers = {
    "Authorization": "Bearer easyslang-api-secret-key-2024",
    "Content-Type": "application/json"
}
data = {
    "text": "Hello, how are you today?",
    "fromLanguage": "English",
    "toLanguage": "Korean"
}

response = requests.post(url, headers=headers, json=data)
print(response.json())
```

## 프로젝트 구조

```
voice-backend/
├── main.py                 # FastAPI 애플리케이션 엔트리포인트
├── requirements.txt        # Python 의존성
├── railway.toml           # Railway 배포 설정
├── Procfile              # 프로세스 시작 명령
├── .env                  # 환경 변수
├── config/
│   ├── __init__.py
│   └── settings.py       # 애플리케이션 설정
├── models/
│   ├── __init__.py
│   └── api_models.py     # API 요청/응답 모델
├── services/
│   ├── __init__.py
│   └── openai_service.py # OpenAI API 서비스
└── routers/
    ├── __init__.py
    └── translate.py      # 번역 API 라우터
```

## 보안 고려사항

- API 키는 환경 변수로 관리
- Bearer 토큰 기반 인증
- CORS 설정 (프로덕션에서는 특정 도메인으로 제한 권장)
- 입력 데이터 검증

## 모니터링

- `/health` 엔드포인트로 서버 상태 확인
- 로깅을 통한 API 호출 추적
- Railway 대시보드에서 서버 메트릭 모니터링

## 향후 개발 계획

- 대화 응답 생성 API 추가
- 환영 메시지 생성 API 추가
- 음성 합성 (TTS) API 추가
- 사용량 추적 및 제한
- 캐싱 시스템 도입 