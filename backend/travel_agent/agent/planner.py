"""Deprecated planner node kept for compatibility with the old workflow."""

from __future__ import annotations

import re

from travel_agent.agent.state import AgentState


_LOCATION_PATTERNS = [
    r'从(?P<origin>[^，。；,]+?)到(?P<destination>[^，。；,]+)',
    r'从(?P<origin>[^，。；,]+?)去(?P<destination>[^，。；,]+)',
    r'(?P<origin>[^，。；,]+?)到(?P<destination>[^，。；,]+)',
    r'(?P<origin>[^，。；,]+?)去(?P<destination>[^，。；,]+)',
]

_SCENARIO_KEYWORDS = {
    'travel_tourism': ('旅游', '旅行', '旅行方案', '旅游规划', '景区', '酒店', '住宿', '餐厅', '周末', '度假', '游玩', '景点', '行程', '必去'),
    'daily_commute': ('上班', '通勤', '公司', '上学'),
    'navigation': ('怎么走', '路线', '出行', '规划', '前往', '到'),
}


def _clean_location(value: str) -> str:
    text = value.strip().strip('，。；,！？ ')
    for suffix in ('出发', '出发地', '目的地', '去', '到', '前往', '回到'):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or value.strip()


def _extract_location_entities(question: str) -> dict[str, str]:
    text = question.strip()
    for pattern in _LOCATION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            origin = _clean_location(match.group('origin'))
            destination = _clean_location(match.group('destination'))
            if origin and destination:
                return {'origin': origin, 'destination': destination}
    return {'origin': '起点', 'destination': '终点'}


def _infer_scenario(question: str, image_context: dict | None = None) -> str:
    text = f'{question} {image_context or {}}'
    if re.search(r'(\d+|[一二两三四五六七八九十]+)\s*天\s*(\d+|[一二两三四五六七八九十]+)?\s*晚', text):
        return 'travel_tourism'
    for scenario, keywords in _SCENARIO_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return scenario
    return 'general_trip'


class PlannerNode:
    def __call__(self, state: AgentState) -> AgentState:
        question = state.get('question', '')
        image_context = state.get('image_context')
        location_entities = _extract_location_entities(question)
        scenario = _infer_scenario(question, image_context)
        plan = [
            '识别起终点和出行方式',
            '根据用户偏好选择合适路线类型',
            '调用地图服务获取真实路线',
            '核验数据来源与可信度',
            '生成可直接执行的路线建议',
        ]
        if scenario == 'travel_tourism':
            plan.insert(2, '结合旅游场景优化路线与景点顺序')
        if scenario == 'daily_commute':
            plan.insert(2, '结合通勤场景优化换乘与耗时')
        return {
            **state,
            'intent': 'travel_planning' if question else 'general_chat',
            'scenario': scenario,
            'plan': plan,
            'location_entities': location_entities,
            'processing_notes': [*(state.get('processing_notes') or []), f'planner:scenario={scenario}'],
        }
