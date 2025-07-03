#!/usr/bin/env python3
"""
템플릿 사용 기록을 추적하고 다양성을 보장하는 매니저
"""
import time
import random
from typing import Dict, List, Set, Optional
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)

class TemplateHistoryManager:
    """
    템플릿 사용 기록을 추적하고 반복을 방지하는 매니저
    """
    
    def __init__(self, max_history_size: int = 10):
        self.max_history_size = max_history_size
        
        # 카테고리별 최근 사용 기록 (최근 N개)
        self.recent_reactions: deque = deque(maxlen=max_history_size)
        self.recent_emotions: deque = deque(maxlen=max_history_size)
        self.recent_continuations: deque = deque(maxlen=max_history_size)
        self.recent_starters: deque = deque(maxlen=max_history_size)
        self.recent_greetings: deque = deque(maxlen=max_history_size)
        
        # 텍스트별 사용 횟수 추적
        self.usage_count: Dict[str, int] = defaultdict(int)
        
        # 마지막 사용 시간 추적
        self.last_used: Dict[str, float] = {}
        
        # 연속 사용 방지 (직전에 사용한 것들)
        self.last_reaction: Optional[str] = None
        self.last_emotion: Optional[str] = None
        self.last_continuation: Optional[str] = None
        self.last_starter: Optional[str] = None
        self.last_greeting: Optional[str] = None
        
    def select_diverse_template(self, 
                               templates: List[str], 
                               category: str,
                               avoid_recent: bool = True,
                               prefer_less_used: bool = True) -> str:
        """
        다양성을 고려하여 템플릿을 선택합니다.
        
        Args:
            templates: 선택 가능한 템플릿 리스트
            category: 카테고리 ('reaction', 'emotion', 'continuation')
            avoid_recent: 최근 사용한 것들을 피할지 여부
            prefer_less_used: 적게 사용된 것들을 우선할지 여부
        """
        if not templates:
            return ""
            
        if len(templates) == 1:
            self._record_usage(templates[0], category)
            return templates[0]
        
        # 1. 최근 사용된 것들 필터링
        available_templates = list(templates)
        
        if avoid_recent:
            recent_history = self._get_recent_history(category)
            # 최근 사용된 것들 제외 (단, 전체가 제외되지 않도록)
            non_recent = [t for t in templates if t not in recent_history]
            if non_recent:  # 최근 사용되지 않은 것이 있으면 그것들만 고려
                available_templates = non_recent
                logger.info(f"{category}: 최근 사용 {len(recent_history)}개 제외, {len(available_templates)}개 후보")
        
        # 2. 직전 사용한 것과 동일한 것 제외
        last_used = self._get_last_used(category)
        if last_used and last_used in available_templates and len(available_templates) > 1:
            available_templates = [t for t in available_templates if t != last_used]
            logger.info(f"{category}: 직전 사용 템플릿 제외")
        
        # 3. 사용 빈도 기반 가중치 적용
        if prefer_less_used and len(available_templates) > 1:
            selected = self._select_by_usage_weight(available_templates)
        else:
            # 단순 무작위 선택
            selected = random.choice(available_templates)
        
        # 4. 사용 기록
        self._record_usage(selected, category)
        
        logger.info(f"{category} 템플릿 선택: '{selected[:30]}...' (총 {len(templates)}개 중)")
        return selected
    
    def _get_recent_history(self, category: str) -> Set[str]:
        """카테고리별 최근 사용 기록 반환"""
        if category == 'reaction':
            return set(self.recent_reactions)
        elif category == 'emotion':
            return set(self.recent_emotions)
        elif category == 'continuation':
            return set(self.recent_continuations)
        elif category == 'starter':
            return set(self.recent_starters)
        elif category == 'greeting':
            return set(self.recent_greetings)
        return set()
    
    def _get_last_used(self, category: str) -> Optional[str]:
        """카테고리별 마지막 사용 템플릿 반환"""
        if category == 'reaction':
            return self.last_reaction
        elif category == 'emotion':
            return self.last_emotion
        elif category == 'continuation':
            return self.last_continuation
        elif category == 'starter':
            return self.last_starter
        elif category == 'greeting':
            return self.last_greeting
        return None
    
    def _record_usage(self, template: str, category: str):
        """템플릿 사용 기록"""
        current_time = time.time()
        
        # 사용 횟수 증가
        self.usage_count[template] += 1
        
        # 마지막 사용 시간 기록
        self.last_used[template] = current_time
        
        # 카테고리별 최근 사용 기록 추가
        if category == 'reaction':
            self.recent_reactions.append(template)
            self.last_reaction = template
        elif category == 'emotion':
            self.recent_emotions.append(template)
            self.last_emotion = template
        elif category == 'continuation':
            self.recent_continuations.append(template)
            self.last_continuation = template
        elif category == 'starter':
            self.recent_starters.append(template)
            self.last_starter = template
        elif category == 'greeting':
            self.recent_greetings.append(template)
            self.last_greeting = template
    
    def _select_by_usage_weight(self, templates: List[str]) -> str:
        """
        사용 빈도에 반비례하는 가중치로 선택
        적게 사용된 것일수록 선택될 확률이 높음
        """
        if len(templates) == 1:
            return templates[0]
        
        # 각 템플릿의 사용 횟수 (0이면 1로 처리)
        usage_counts = [max(1, self.usage_count.get(t, 0)) for t in templates]
        
        # 역가중치 계산 (적게 사용된 것일수록 높은 가중치)
        max_usage = max(usage_counts)
        weights = [max_usage - count + 1 for count in usage_counts]
        
        # 가중치 기반 선택
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(templates)
        
        # 누적 확률로 선택
        rand_value = random.uniform(0, total_weight)
        cumulative = 0
        
        for i, weight in enumerate(weights):
            cumulative += weight
            if rand_value <= cumulative:
                selected = templates[i]
                usage_info = f"사용횟수: {self.usage_count.get(selected, 0)}"
                logger.info(f"가중치 선택: {selected[:20]}... ({usage_info})")
                return selected
        
        # 폴백
        return templates[-1]
    
    def get_usage_stats(self) -> Dict:
        """사용 통계 반환"""
        return {
            "total_templates_used": len(self.usage_count),
            "recent_reactions": len(self.recent_reactions),
            "recent_emotions": len(self.recent_emotions), 
            "recent_continuations": len(self.recent_continuations),
            "recent_starters": len(self.recent_starters),
            "recent_greetings": len(self.recent_greetings),
            "most_used": sorted(self.usage_count.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    
    def reset_history(self):
        """기록 초기화"""
        self.recent_reactions.clear()
        self.recent_emotions.clear()
        self.recent_continuations.clear()
        self.recent_starters.clear()
        self.recent_greetings.clear()
        self.usage_count.clear()
        self.last_used.clear()
        self.last_reaction = None
        self.last_emotion = None
        self.last_continuation = None
        self.last_starter = None
        self.last_greeting = None
        logger.info("템플릿 사용 기록 초기화 완료") 