# 🚀 Supabase 로깅 시스템 설정 가이드

Flow-Chat API는 대화 내용과 사용자 입력을 체계적으로 저장하기 위해 Supabase 데이터베이스를 사용합니다.

## 📋 목차

1. [Supabase 프로젝트 생성](#1-supabase-프로젝트-생성)
2. [환경 변수 설정](#2-환경-변수-설정)
3. [테이블 초기화](#3-테이블-초기화)
4. [저장되는 데이터 구조](#4-저장되는-데이터-구조)
5. [API 엔드포인트](#5-api-엔드포인트)
6. [분석 및 모니터링](#6-분석-및-모니터링)

---

## 1. Supabase 프로젝트 생성

### 1.1 계정 생성 및 프로젝트 설정

1. [Supabase 웹사이트](https://supabase.com) 방문
2. 계정 생성 또는 로그인
3. "New Project" 클릭
4. 프로젝트 이름: `voice-backend-logs` (또는 원하는 이름)
5. 데이터베이스 비밀번호 설정
6. 지역 선택 (가까운 지역 권장)
7. "Create new project" 클릭

### 1.2 API 키 확인

프로젝트 생성 후:
1. 왼쪽 사이드바에서 **Settings** → **API** 클릭
2. 다음 정보 복사:
   - **Project URL**: `https://your-project-id.supabase.co`
   - **anon public**: API 키 (public 용도)

---

## 2. 환경 변수 설정

### 2.1 .env 파일 생성

프로젝트 루트에 `.env` 파일을 생성하고 다음 내용을 추가:

```bash
# Supabase Configuration
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-key-here

# OpenAI Configuration (기존)
OPENAI_API_KEY=your-openai-api-key

# R2 Configuration (기존)
R2_ACCOUNT_ID=your-r2-account-id
R2_ACCESS_KEY_ID=your-r2-access-key
R2_SECRET_ACCESS_KEY=your-r2-secret-key
R2_BUCKET_NAME=your-r2-bucket-name

# Application Settings
DEBUG=true
LOG_LEVEL=INFO
```

### 2.2 python-dotenv 설치 (권장)

```bash
pip install python-dotenv
```

---

## 3. 테이블 초기화

### 3.1 자동 초기화 스크립트 실행

```bash
python scripts/init_supabase.py
```

스크립트가 자동으로:
- 연결 테스트
- 필요한 테이블 생성
- 인덱스 생성
- 테스트 데이터 생성 (선택사항)

### 3.2 수동 테이블 생성 (선택사항)

Supabase 대시보드의 SQL Editor에서 다음 쿼리 실행:

```sql
-- 대화 세션 테이블
CREATE TABLE conversation_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    user_id TEXT,
    emotion TEXT NOT NULL,
    topic TEXT,
    sub_topic TEXT,
    keyword TEXT,
    from_lang TEXT NOT NULL,
    to_lang TEXT NOT NULL,
    session_start TIMESTAMPTZ NOT NULL,
    session_end TIMESTAMPTZ,
    total_turns INTEGER DEFAULT 0,
    completion_status TEXT DEFAULT 'in_progress',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 대화 턴 테이블
CREATE TABLE conversation_turns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    user_input TEXT NOT NULL,
    ai_response TEXT NOT NULL,
    learned_expressions JSONB,
    stage TEXT NOT NULL,
    processing_time_ms FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id)
);

-- 분석 이벤트 테이블
CREATE TABLE conversation_analytics (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 일일 통계 테이블
CREATE TABLE daily_stats (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    total_sessions INTEGER DEFAULT 0,
    completed_sessions INTEGER DEFAULT 0,
    abandoned_sessions INTEGER DEFAULT 0,
    total_conversation_turns INTEGER DEFAULT 0,
    emotions JSONB,
    topics JSONB,
    language_pairs JSONB,
    total_learned_expressions INTEGER DEFAULT 0,
    avg_session_duration FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. 저장되는 데이터 구조

### 4.1 대화 세션 (conversation_sessions)

```json
{
  "session_id": "uuid-string",
  "emotion": "happy",
  "topic": "travel",
  "sub_topic": "vacation planning", 
  "keyword": "adventure",
  "from_lang": "korean",
  "to_lang": "english",
  "session_start": "2024-01-15T10:00:00Z",
  "session_end": "2024-01-15T10:15:00Z",
  "total_turns": 5,
  "completion_status": "completed"
}
```

### 4.2 대화 턴 (conversation_turns)

```json
{
  "session_id": "uuid-string",
  "turn_number": 1,
  "timestamp": "2024-01-15T10:01:00Z",
  "user_input": "I went to the beach yesterday",
  "ai_response": "That sounds wonderful! 해변에서 즐거운 시간을 보내셨군요!",
  "learned_expressions": [
    {
      "word": "had a blast",
      "meaning": "정말 즐거웠다",
      "pronunciation": "해드 어 블래스트",
      "example": "I had a blast at the party!"
    }
  ],
  "stage": "paraphrase",
  "processing_time_ms": 1250.5
}
```

### 4.3 분석 이벤트 (conversation_analytics)

```json
{
  "session_id": "uuid-string",
  "event_type": "conversation_completed",
  "timestamp": "2024-01-15T10:15:00Z",
  "details": {
    "total_turns": 5,
    "learned_expressions_count": 8,
    "duration_seconds": 900
  }
}
```

### 4.4 일일 통계 (daily_stats)

```json
{
  "date": "2024-01-15",
  "total_sessions": 45,
  "completed_sessions": 38,
  "abandoned_sessions": 7,
  "total_conversation_turns": 298,
  "emotions": {"happy": 15, "sad": 8, "excited": 12},
  "topics": {"travel": 10, "food": 8, "hobby": 15},
  "language_pairs": {"korean-english": 40, "english-korean": 5},
  "total_learned_expressions": 156
}
```

---

## 5. API 엔드포인트

### 5.1 대화 로그 조회

```bash
GET /v1/ai/flow-chat/conversation-logs/{session_id}
```

**응답 예시:**
```json
{
  "session_data": {
    "session_id": "abc123",
    "emotion": "happy",
    "total_turns": 5,
    "completion_status": "completed"
  },
  "conversation_turns": [
    {
      "turn_number": 1,
      "user_input": "I love traveling!",
      "ai_response": "여행을 좋아하시는군요! That's wonderful!",
      "learned_expressions": [...]
    }
  ]
}
```

### 5.2 일일 통계 조회

```bash
GET /v1/ai/flow-chat/daily-stats/2024-01-15
```

### 5.3 분석 데이터 조회

```bash
GET /v1/ai/flow-chat/analytics/conversations?emotion=happy&topic=travel&limit=50
```

---

## 6. 분석 및 모니터링

### 6.1 Supabase 대시보드 활용

1. **Table Editor**: 실시간 데이터 확인
2. **SQL Editor**: 커스텀 쿼리 실행
3. **API**: REST API 자동 생성
4. **Auth**: 사용자 인증 (향후 확장)

### 6.2 유용한 분석 쿼리

#### 인기 감정 순위
```sql
SELECT 
  emotion,
  COUNT(*) as session_count,
  AVG(total_turns) as avg_turns
FROM conversation_sessions 
WHERE completion_status = 'completed'
GROUP BY emotion 
ORDER BY session_count DESC;
```

#### 일별 완료율
```sql
SELECT 
  DATE(session_start) as date,
  COUNT(*) as total_sessions,
  SUM(CASE WHEN completion_status = 'completed' THEN 1 ELSE 0 END) as completed,
  ROUND(
    SUM(CASE WHEN completion_status = 'completed' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 
    2
  ) as completion_rate
FROM conversation_sessions 
GROUP BY DATE(session_start)
ORDER BY date DESC;
```

#### 평균 세션 시간
```sql
SELECT 
  emotion,
  AVG(EXTRACT(EPOCH FROM (session_end - session_start))/60) as avg_duration_minutes
FROM conversation_sessions 
WHERE session_end IS NOT NULL
GROUP BY emotion;
```

### 6.3 실시간 모니터링

Supabase는 실시간 구독을 지원하므로 대시보드나 모니터링 도구에서 실시간 데이터 업데이트가 가능합니다.

---

## 🔧 문제 해결

### 연결 오류

1. **환경 변수 확인**: `.env` 파일의 URL과 KEY가 정확한지 확인
2. **네트워크 확인**: 방화벽이나 VPN 설정 확인
3. **Supabase 상태**: [Supabase 상태 페이지](https://status.supabase.com) 확인

### 테이블 생성 오류

1. **권한 확인**: anon key로는 RPC 함수 실행이 제한될 수 있음
2. **수동 생성**: Supabase 대시보드에서 직접 SQL 실행
3. **서비스 키**: 필요 시 service_role 키 사용 (보안 주의)

### 성능 최적화

1. **인덱스 확인**: 쿼리 성능이 느리면 추가 인덱스 생성
2. **데이터 정리**: 오래된 데이터는 정기적으로 아카이브
3. **Connection Pool**: 높은 부하 시 연결 풀 설정

---

## 📚 추가 자료

- [Supabase 공식 문서](https://supabase.com/docs)
- [PostgreSQL JSON 함수](https://www.postgresql.org/docs/current/functions-json.html)
- [Supabase Python Client](https://github.com/supabase-community/supabase-py)

---

이제 Flow-Chat API의 모든 대화 내용이 Supabase에 체계적으로 저장되고, 실시간 분석과 모니터링이 가능합니다! 🎉 