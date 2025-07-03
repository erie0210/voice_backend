import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from pydantic import BaseModel

from models.api_models import LearnWord

# 로깅 설정
logger = logging.getLogger(__name__)

class SupabaseService:
    def __init__(self):
        self.url: str = os.environ.get("SUPABASE_URL", "")
        self.key: str = os.environ.get("SUPABASE_KEY", "")
        self.client: Optional[Client] = None
        
        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                logger.info("[SUPABASE] Successfully connected to Supabase")
            except Exception as e:
                logger.error(f"[SUPABASE] Failed to connect: {str(e)}")
                self.client = None
        else:
            logger.warning("[SUPABASE] Missing URL or KEY in environment variables")
    
    async def create_tables(self):
        """Create necessary tables for conversation logging"""
        if not self.client:
            logger.error("[SUPABASE] Client not initialized")
            return False
        
        try:
            # Create conversation_sessions table
            sessions_sql = """
            CREATE TABLE IF NOT EXISTS conversation_sessions (
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
            """
            
            # Create conversation_turns table
            turns_sql = """
            CREATE TABLE IF NOT EXISTS conversation_turns (
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
            """
            
            # Create conversation_analytics table
            analytics_sql = """
            CREATE TABLE IF NOT EXISTS conversation_analytics (
                id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                details JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
            
            # Create daily_stats table
            daily_stats_sql = """
            CREATE TABLE IF NOT EXISTS daily_stats (
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
            """
            
            # Create indexes for better performance
            indexes_sql = [
                "CREATE INDEX IF NOT EXISTS idx_conversation_turns_session_id ON conversation_turns(session_id);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_turns_timestamp ON conversation_turns(timestamp);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_emotion ON conversation_sessions(emotion);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_topic ON conversation_sessions(topic);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_created_at ON conversation_sessions(created_at);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_analytics_session_id ON conversation_analytics(session_id);",
                "CREATE INDEX IF NOT EXISTS idx_conversation_analytics_event_type ON conversation_analytics(event_type);",
            ]
            
            # Execute table creation
            self.client.rpc('exec_sql', {'sql': sessions_sql}).execute()
            self.client.rpc('exec_sql', {'sql': turns_sql}).execute()
            self.client.rpc('exec_sql', {'sql': analytics_sql}).execute()
            self.client.rpc('exec_sql', {'sql': daily_stats_sql}).execute()
            
            # Execute index creation
            for index_sql in indexes_sql:
                try:
                    self.client.rpc('exec_sql', {'sql': index_sql}).execute()
                except Exception as e:
                    logger.warning(f"[SUPABASE] Index creation warning: {str(e)}")
            
            logger.info("[SUPABASE] Tables and indexes created successfully")
            return True
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to create tables: {str(e)}")
            return False
    
    async def save_conversation_session(self, session_data: Dict[str, Any]) -> bool:
        """Save or update conversation session"""
        if not self.client:
            return False
        
        try:
            # Check if session exists
            existing = self.client.table('conversation_sessions').select('session_id').eq('session_id', session_data['session_id']).execute()
            
            if existing.data:
                # Update existing session
                result = self.client.table('conversation_sessions').update({
                    'session_end': session_data.get('session_end'),
                    'total_turns': session_data.get('total_turns', 0),
                    'completion_status': session_data.get('completion_status', 'in_progress'),
                    'updated_at': datetime.now().isoformat()
                }).eq('session_id', session_data['session_id']).execute()
            else:
                # Insert new session
                result = self.client.table('conversation_sessions').insert({
                    'session_id': session_data['session_id'],
                    'user_id': session_data.get('user_id'),
                    'emotion': session_data['emotion'],
                    'topic': session_data.get('topic'),
                    'sub_topic': session_data.get('sub_topic'),
                    'keyword': session_data.get('keyword'),
                    'from_lang': session_data['from_lang'],
                    'to_lang': session_data['to_lang'],
                    'session_start': session_data['session_start'],
                    'session_end': session_data.get('session_end'),
                    'total_turns': session_data.get('total_turns', 0),
                    'completion_status': session_data.get('completion_status', 'in_progress')
                }).execute()
            
            logger.info(f"[SUPABASE] Session saved: {session_data['session_id']}")
            return True
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to save session: {str(e)}")
            return False
    
    async def save_conversation_turn(self, turn_data: Dict[str, Any]) -> bool:
        """Save conversation turn"""
        if not self.client:
            return False
        
        try:
            # Convert learned expressions to JSON
            learned_expressions_json = None
            if turn_data.get('learned_expressions'):
                if isinstance(turn_data['learned_expressions'], list):
                    learned_expressions_json = [
                        expr.dict() if hasattr(expr, 'dict') else expr 
                        for expr in turn_data['learned_expressions']
                    ]
                else:
                    learned_expressions_json = turn_data['learned_expressions']
            
            result = self.client.table('conversation_turns').insert({
                'session_id': turn_data['session_id'],
                'turn_number': turn_data['turn_number'],
                'timestamp': turn_data['timestamp'],
                'user_input': turn_data['user_input'],
                'ai_response': turn_data['ai_response'],
                'learned_expressions': learned_expressions_json,
                'stage': turn_data['stage'],
                'processing_time_ms': turn_data.get('processing_time_ms', 0)
            }).execute()
            
            logger.info(f"[SUPABASE] Turn saved: {turn_data['session_id']} turn {turn_data['turn_number']}")
            return True
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to save turn: {str(e)}")
            return False
    
    async def save_conversation_analytics(self, analytics_data: Dict[str, Any]) -> bool:
        """Save conversation analytics event"""
        if not self.client:
            return False
        
        try:
            result = self.client.table('conversation_analytics').insert({
                'session_id': analytics_data['session_id'],
                'event_type': analytics_data['event_type'],
                'timestamp': analytics_data['timestamp'],
                'details': analytics_data.get('details', {})
            }).execute()
            
            logger.info(f"[SUPABASE] Analytics saved: {analytics_data['session_id']} - {analytics_data['event_type']}")
            return True
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to save analytics: {str(e)}")
            return False
    
    async def update_daily_stats(self, date: str, stats_data: Dict[str, Any]) -> bool:
        """Update daily statistics"""
        if not self.client:
            return False
        
        try:
            # Check if stats for this date exist
            existing = self.client.table('daily_stats').select('date').eq('date', date).execute()
            
            if existing.data:
                # Update existing stats
                result = self.client.table('daily_stats').update({
                    'total_sessions': stats_data.get('total_sessions', 0),
                    'completed_sessions': stats_data.get('completed_sessions', 0),
                    'abandoned_sessions': stats_data.get('abandoned_sessions', 0),
                    'total_conversation_turns': stats_data.get('total_conversation_turns', 0),
                    'emotions': stats_data.get('emotions', {}),
                    'topics': stats_data.get('topics', {}),
                    'language_pairs': stats_data.get('language_pairs', {}),
                    'total_learned_expressions': stats_data.get('total_learned_expressions', 0),
                    'avg_session_duration': stats_data.get('avg_session_duration', 0),
                    'updated_at': datetime.now().isoformat()
                }).eq('date', date).execute()
            else:
                # Insert new stats
                result = self.client.table('daily_stats').insert({
                    'date': date,
                    'total_sessions': stats_data.get('total_sessions', 0),
                    'completed_sessions': stats_data.get('completed_sessions', 0),
                    'abandoned_sessions': stats_data.get('abandoned_sessions', 0),
                    'total_conversation_turns': stats_data.get('total_conversation_turns', 0),
                    'emotions': stats_data.get('emotions', {}),
                    'topics': stats_data.get('topics', {}),
                    'language_pairs': stats_data.get('language_pairs', {}),
                    'total_learned_expressions': stats_data.get('total_learned_expressions', 0),
                    'avg_session_duration': stats_data.get('avg_session_duration', 0)
                }).execute()
            
            logger.info(f"[SUPABASE] Daily stats updated for {date}")
            return True
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to update daily stats: {str(e)}")
            return False
    
    async def get_conversation_log(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get conversation log by session ID"""
        if not self.client:
            return None
        
        try:
            # Get session info
            session_result = self.client.table('conversation_sessions').select('*').eq('session_id', session_id).execute()
            
            if not session_result.data:
                return None
            
            session_data = session_result.data[0]
            
            # Get conversation turns
            turns_result = self.client.table('conversation_turns').select('*').eq('session_id', session_id).order('turn_number').execute()
            
            return {
                'session_data': session_data,
                'conversation_turns': turns_result.data
            }
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to get conversation log: {str(e)}")
            return None
    
    async def get_daily_stats(self, date: str) -> Optional[Dict[str, Any]]:
        """Get daily statistics"""
        if not self.client:
            return None
        
        try:
            result = self.client.table('daily_stats').select('*').eq('date', date).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to get daily stats: {str(e)}")
            return None
    
    async def get_conversation_analytics(self, filters: Dict[str, Any] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get conversation analytics with filters"""
        if not self.client:
            return []
        
        try:
            query = self.client.table('conversation_analytics').select('*')
            
            if filters:
                if filters.get('session_id'):
                    query = query.eq('session_id', filters['session_id'])
                if filters.get('event_type'):
                    query = query.eq('event_type', filters['event_type'])
                if filters.get('start_date'):
                    query = query.gte('timestamp', filters['start_date'])
                if filters.get('end_date'):
                    query = query.lte('timestamp', filters['end_date'])
            
            result = query.order('timestamp', desc=True).limit(limit).execute()
            return result.data
            
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to get analytics: {str(e)}")
            return []

# Global instance
supabase_service = SupabaseService() 