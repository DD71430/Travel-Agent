from __future__ import annotations

import re
from typing import Literal

NEARBY_KEYWORDS = ('附近', '周边', '周围', '旁边', '临近', '靠近')
CITY_HINTS = ('北京', '上海', '广州', '深圳', '杭州', '济南', '南京', '苏州', '成都', '重庆', '武汉', '西安', '天津', '青岛', '厦门', '长沙', '郑州', '合肥', '福州', '昆明', '哈尔滨', '大连', '宁波', '无锡', '佛山', '东莞', '烟台', '珠海', '南昌', '徐州', '泰安', '德州', '曲阜')

_LOCATION_PATTERNS = [
    r'从(?P<origin>[^，。；,]+?)(?:自驾|驾车|开车|公交|公共交通|地铁|骑行|步行|徒步)?到(?P<destination>[^，。；,]+)',
    r'从(?P<origin>[^，。；,]+?)(?:自驾|驾车|开车|公交|公共交通|地铁|骑行|步行|徒步)?去(?P<destination>[^，。；,]+)',
    r'从(?P<origin>[^，。；,]+?)到(?P<destination>[^，。；,]+)',
    r'从(?P<origin>[^，。；,]+?)去(?P<destination>[^，。；,]+)',
    r'(?P<origin>[^，。；,]+?)到(?P<destination>[^，。；,]+)',
    r'(?P<origin>[^，。；,]+?)去(?P<destination>[^，。；,]+)',
]
_COMMON_PREFIXES = ('帮我规划', '请帮我规划', '帮我做', '请帮我做', '帮我', '请帮我', '请', '给我', '为我', '我想', '想', '安排', '规划', '做个', '做一份')
_TRAVEL_NOISE_WORDS = ('旅行', '旅游', '行程', '游玩', '度假', '自由行', '攻略', '方案', '线路')
_LOCATION_TRAILING_PATTERN = re.compile(
    r'(?:玩|游|待|住)?\s*(?:\d+\s*天(?:\d+\s*晚)?|[一二两三四五六七八九十]+\s*天(?:[一二两三四五六七八九十]+\s*晚)?|\d+\s*晚|[一二两三四五六七八九十]+\s*晚|周末|双休日).*$|预算\s*\d+.*$|自驾.*$|驾车.*$|公交.*$|地铁.*$|步行.*$|骑行.*$',
)
_CHINESE_NUMERAL_MAP = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def strip_common_noise(text: str) -> str:
    cleaned = text.strip()
    for phrase in _COMMON_PREFIXES:
        cleaned = cleaned.replace(phrase, '')
    for word in _TRAVEL_NOISE_WORDS:
        cleaned = cleaned.replace(word, '')
    return cleaned.strip('的').strip()


def clean_location(value: str) -> str:
    text = strip_common_noise(value.strip().strip('，。；,！？ '))
    text = text.replace('从', '').replace('去', '').replace('到', '')
    text = text.replace('→', '').replace('->', '').replace('-->', '').strip()
    text = re.sub(r'(自驾|驾车|开车|公交|公共交通|地铁|骑行|步行|徒步)$', '', text).strip()
    text = re.sub(r'进行为期.*$', '', text).strip()
    text = re.sub(r'的\d+\s*天.*$', '', text).strip()
    text = re.sub(r'\d+\s*天.*$', '', text).strip()
    text = _LOCATION_TRAILING_PATTERN.sub('', text).strip()
    text = text.strip('的').strip()
    for suffix in ('出发地', '目的地', '出发', '去', '到', '前往', '回到', '一带', '附近'):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or value.strip()


def extract_locations(question: str) -> tuple[str | None, str | None]:
    raw_text = strip_common_noise(question.strip())
    for candidate_text in (raw_text, _LOCATION_TRAILING_PATTERN.sub('', raw_text).strip()):
        for pattern in _LOCATION_PATTERNS:
            match = re.search(pattern, candidate_text)
            if match:
                origin = clean_location(match.group('origin'))
                destination = clean_location(match.group('destination'))
                if origin and destination:
                    return origin, destination
    cleaned_text = _LOCATION_TRAILING_PATTERN.sub('', raw_text).strip()
    for separator in ('到', '去', '→'):
        if separator in cleaned_text and len(cleaned_text.split(separator)) == 2:
            origin, destination = cleaned_text.split(separator, 1)
            origin = clean_location(origin)
            destination = clean_location(destination)
            if origin and destination:
                return origin, destination
    return None, None


def _parse_chinese_number(text: str) -> int | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if cleaned in _CHINESE_NUMERAL_MAP:
        return _CHINESE_NUMERAL_MAP[cleaned]
    if cleaned.startswith('十') and len(cleaned) == 2:
        return 10 + _CHINESE_NUMERAL_MAP.get(cleaned[1], 0)
    if cleaned.endswith('十') and len(cleaned) == 2:
        return _CHINESE_NUMERAL_MAP.get(cleaned[0], 0) * 10
    if '十' in cleaned and len(cleaned) == 3:
        return _CHINESE_NUMERAL_MAP.get(cleaned[0], 0) * 10 + _CHINESE_NUMERAL_MAP.get(cleaned[2], 0)
    return None


def extract_trip_details(text: str | None) -> dict[str, str | None]:
    source = text or ''
    duration_match = re.search(r'(\d+)\s*天', source)
    chinese_duration_match = re.search(r'([一二两三四五六七八九十]+)\s*天', source)
    budget_match = re.search(r'预算\s*(\d+)|(?:总预算|花费|控制在)\s*(\d+)', source)
    nights_match = re.search(r'(\d+)\s*晚', source)
    chinese_nights_match = re.search(r'([一二两三四五六七八九十]+)\s*晚', source)
    duration_days = duration_match.group(1) if duration_match else None
    if not duration_days and chinese_duration_match:
        parsed = _parse_chinese_number(chinese_duration_match.group(1))
        duration_days = str(parsed) if parsed is not None else None
    nights = nights_match.group(1) if nights_match else None
    if not nights and chinese_nights_match:
        parsed = _parse_chinese_number(chinese_nights_match.group(1))
        nights = str(parsed) if parsed is not None else None
    return {'duration_days': duration_days, 'budget': (budget_match.group(1) or budget_match.group(2)) if budget_match else None, 'nights': nights}


def extract_travel_mode(text: str | None, fallback: str | None = None) -> str:
    source = text or ''
    if any(keyword in source for keyword in ('公交', '地铁', '公共交通', '巴士', '大巴', '换乘', '高铁', '动车', '火车', '列车', '铁路', '飞机', '航班', '机场', '长途汽车', '客车')):
        return 'transit'
    if any(keyword in source for keyword in ('骑行', '单车', '自行车')):
        return 'bicycling'
    if any(keyword in source for keyword in ('步行', '走路', '徒步')):
        return 'walking'
    if any(keyword in source for keyword in ('自驾', '驾车', '开车', '租车')):
        return 'driving'
    return fallback or 'driving'


def extract_interest_keywords(text: str | None) -> list[str]:
    source = text or ''
    patterns = [r'沿途(?:想看|想去|希望安排|顺路看)(?P<items>[^，。；,]+)', r'想看(?P<items>[^，。；,]+)', r'想去(?P<items>[^，。；,]+)', r'喜欢(?P<items>[^，。；,]+)', r'偏好(?P<items>[^，。；,]+)']
    stopwords = {'一下', '一个', '一些', '看看', '安排', '路线', '行程', '景点'}
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            for item in re.split(r'[和及、,，/\s]+', match.group('items')):
                cleaned = re.sub(r'^(看看|看|去|逛|安排)', '', item.strip('，。；,！？ ')).strip()
                cleaned = re.sub(r'(即可|就行|就好|为主)$', '', cleaned).strip()
                if cleaned and len(cleaned) > 1 and cleaned not in stopwords and cleaned not in found:
                    found.append(cleaned)
    return found[:6]


def extract_weather_preferences(text: str | None) -> list[str]:
    source = text or ''
    mapping = {'避暑': '希望避暑，优先安排室内或清凉路线', '凉快': '偏好凉爽天气出行', '下雨': '希望兼顾雨天可执行方案', '雨天': '希望兼顾雨天可执行方案', '晴天': '偏好晴天观景路线', '高温': '尽量避开高温暴晒时段', '不想淋雨': '尽量避开降雨时段'}
    return [description for keyword, description in mapping.items() if keyword in source]


def extract_question_waypoints(text: str | None) -> list[dict[str, str]]:
    source = text or ''
    waypoints: list[dict[str, str]] = []
    for pattern in (r'途经(?P<items>[^，。；,]+)', r'顺路去(?P<items>[^，。；,]+)', r'中途想去(?P<items>[^，。；,]+)'):
        for match in re.finditer(pattern, source):
            for item in re.split(r'[和及、,，/]+', match.group('items')):
                cleaned = re.sub(r'(看|去|逛|经过)$', '', item.strip()).strip()
                if cleaned and len(cleaned) > 1 and not any(existing['name'] == cleaned for existing in waypoints):
                    waypoints.append({'name': cleaned})
    return waypoints[:5]


def looks_like_general_chat(question: str) -> bool:
    cleaned = (question or '').strip()
    if not cleaned:
        return False
    lower_cleaned = cleaned.lower()
    general_markers = ('你好', '您好', '你是谁', '你是做什么的', '你能做什么', '介绍一下你自己', '在吗', '早上好', '晚上好', '解释', '说明', '翻译', '总结', '概括', '提取', '分析', '润色', '改写', '整理', '回答', '什么意思', '怎么理解', '为什么', '帮我看看', '帮我写', '帮我改', 'hello', 'hi', 'help', 'what', 'why', 'translate', 'summarize', 'summary', 'explain', 'rewrite', 'polish')
    travel_markers = (*_TRAVEL_NOISE_WORDS, '路线', '路书', '攻略', '怎么去', '怎么走', '出发', '目的地', '途经', '一日游', '两天一晚', '三天两晚', '附近', '周边', '酒店', '餐厅', '景点')
    if any(marker in lower_cleaned for marker in ('hello', 'hi', 'help', 'translate', 'summarize', 'summary', 'explain', 'rewrite', 'polish', 'what', 'why')):
        return True
    if any(marker in cleaned for marker in general_markers):
        return True
    if any(marker in cleaned for marker in travel_markers):
        return False
    return len(cleaned) <= 80


def _looks_like_weather_query(question: str) -> bool:
    source = question or ''
    if not source.strip():
        return False
    if any(keyword in source for keyword in ('天气接口', '腾讯天气', '查天气')):
        return True
    weather_markers = ('天气', '气温', '下雨', '降雨', '高温', '暴雨', '雷阵雨')
    if not any(marker in source for marker in weather_markers):
        return False
    planning_markers = (*_TRAVEL_NOISE_WORDS, '路线', '路书', '攻略', '怎么去', '怎么走', '出发', '目的地', '途经', '一日游', '两天一晚', '三天两晚')
    if any(marker in source for marker in planning_markers):
        return False
    return True


def classify_chat_intent(question: str) -> Literal['general_chat', 'travel_planning', 'nearby_search', 'weather_query']:
    parsed_origin, parsed_destination = extract_locations(question)
    trip_details = extract_trip_details(question)
    travel_markers = (*_TRAVEL_NOISE_WORDS, '路线', '路书', '攻略', '怎么去', '怎么走', '出发', '目的地', '途经', '一日游', '两天一晚', '三天两晚', '经典景点', '游览节奏')
    if parsed_origin and parsed_destination:
        return 'travel_planning'
    if any(trip_details.values()) and any(keyword in question for keyword in travel_markers):
        return 'travel_planning'
    nearby_target_markers = ('酒店', '餐厅', '美食', '景点', '博物馆', '公园', '商场', '推荐', '民宿', '宾馆')
    if any(keyword in question for keyword in NEARBY_KEYWORDS) and any(keyword in question for keyword in nearby_target_markers):
        return 'nearby_search'
    if _looks_like_weather_query(question):
        return 'weather_query'
    if looks_like_general_chat(question):
        return 'general_chat'
    if any(trip_details.values()):
        return 'travel_planning'
    if any(keyword in question for keyword in travel_markers):
        return 'travel_planning'
    return 'general_chat'
