from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

from routers import translate, chat, tts
from config.settings import settings

# 환경 변수 로드
load_dotenv()

app = FastAPI(
    title="EasySlang AI API",
    description="OpenAI 기반 언어 학습 API 서버",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(translate.router, prefix="/v1/ai", tags=["AI Translation"])
app.include_router(chat.router, prefix="/v1/ai", tags=["AI Chat"])
app.include_router(tts.router, prefix="/v1/ai", tags=["AI TTS"])

@app.get("/")
async def root():
    return {"message": "EasySlang AI API Server", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000))) 