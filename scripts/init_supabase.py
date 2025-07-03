#!/usr/bin/env python3
"""
Supabase 테이블 초기화 스크립트

사용법:
1. .env 파일에 SUPABASE_URL과 SUPABASE_KEY 설정
2. 스크립트 실행: python scripts/init_supabase.py

환경 변수 예시:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
"""

import sys
import os
import asyncio

# 프로젝트 루트를 Python path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.supabase_service import supabase_service

async def init_tables():
    """테이블 생성 및 초기화"""
    print("🚀 Supabase 테이블 초기화 시작...")
    
    if not supabase_service.client:
        print("❌ Supabase 클라이언트 연결 실패!")
        print("   환경 변수 SUPABASE_URL과 SUPABASE_KEY를 확인하세요.")
        return False
    
    try:
        # 테이블 생성
        success = await supabase_service.create_tables()
        
        if success:
            print("✅ 테이블 생성 완료!")
            print("\n📋 생성된 테이블:")
            print("   - conversation_sessions: 대화 세션 정보")
            print("   - conversation_turns: 개별 대화 턴")
            print("   - conversation_analytics: 분석 이벤트")
            print("   - daily_stats: 일일 통계")
            print("\n🔍 인덱스도 생성되었습니다.")
            return True
        else:
            print("❌ 테이블 생성 실패!")
            return False
            
    except Exception as e:
        print(f"❌ 초기화 중 오류 발생: {str(e)}")
        return False

async def test_connection():
    """연결 테스트"""
    print("\n🔌 Supabase 연결 테스트...")
    
    if not supabase_service.client:
        print("❌ 연결 실패")
        return False
    
    try:
        # 간단한 테스트 쿼리
        result = supabase_service.client.table('conversation_sessions').select('count', count='exact').execute()
        print(f"✅ 연결 성공! (현재 세션 수: {result.count})")
        return True
    except Exception as e:
        print(f"❌ 연결 테스트 실패: {str(e)}")
        return False

async def create_test_data():
    """테스트 데이터 생성"""
    print("\n📝 테스트 데이터 생성...")
    
    try:
        # 테스트 세션 데이터
        test_session = {
            'session_id': 'test-session-001',
            'emotion': 'happy',
            'topic': 'travel',
            'sub_topic': 'vacation planning',
            'keyword': 'adventure',
            'from_lang': 'korean',
            'to_lang': 'english',
            'session_start': '2024-01-15T10:00:00Z',
            'total_turns': 0,
            'completion_status': 'in_progress'
        }
        
        await supabase_service.save_conversation_session(test_session)
        
        # 테스트 분석 데이터
        test_analytics = {
            'session_id': 'test-session-001',
            'event_type': 'session_created',
            'timestamp': '2024-01-15T10:00:00Z',
            'details': {'test': True}
        }
        
        await supabase_service.save_conversation_analytics(test_analytics)
        
        print("✅ 테스트 데이터 생성 완료!")
        print("   - 테스트 세션: test-session-001")
        print("   - 테스트 분석 이벤트")
        
    except Exception as e:
        print(f"❌ 테스트 데이터 생성 실패: {str(e)}")

def show_env_example():
    """환경 변수 예시 출력"""
    print("\n📋 환경 변수 설정 예시 (.env 파일):")
    print("""
# Supabase Configuration
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-key-here

# OpenAI Configuration
OPENAI_API_KEY=your-openai-api-key

# Application Settings
DEBUG=true
LOG_LEVEL=INFO
""")

async def main():
    """메인 함수"""
    print("🎯 Flow-Chat Supabase 초기화 도구")
    print("=" * 50)
    
    # 환경 변수 확인
    if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_KEY'):
        print("⚠️  환경 변수가 설정되지 않았습니다!")
        show_env_example()
        return
    
    # 연결 테스트
    connection_ok = await test_connection()
    if not connection_ok:
        show_env_example()
        return
    
    # 테이블 초기화
    init_ok = await init_tables()
    if not init_ok:
        return
    
    # 테스트 데이터 생성 (선택사항)
    response = input("\n❓ 테스트 데이터를 생성하시겠습니까? (y/N): ")
    if response.lower() in ['y', 'yes']:
        await create_test_data()
    
    print("\n🎉 초기화 완료!")
    print("이제 Flow-Chat API가 Supabase에 대화 로그를 저장합니다.")

if __name__ == "__main__":
    # .env 파일 로드 (python-dotenv가 설치된 경우)
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("📁 .env 파일 로드됨")
    except ImportError:
        print("💡 python-dotenv 설치 권장: pip install python-dotenv")
    
    asyncio.run(main()) 