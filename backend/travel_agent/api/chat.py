from __future__ import annotations

from io import BytesIO
import asyncio
import base64
import json
import mimetypes
import re
import tempfile
import uuid
from pathlib import Path

import ffmpeg
import httpx
import websocket
from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader

from travel_agent.core.config import get_settings
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.models.travel import TravelPlanRequest
from travel_agent.agent.travel_graph import unified_graph
from travel_agent.services.chat_planner import ChatRequest
from travel_agent.services.travel_planner import build_travel_plan
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient

NEARBY_KEYWORDS = ('附近', '周边', '酒店', '餐厅', '美食', '景点', '博物馆', '公园', '商场', '推荐')
_CITY_HINTS = ('北京', '上海', '广州', '深圳', '杭州', '济南', '南京', '苏州', '成都', '重庆', '武汉', '西安', '天津', '青岛', '厦门', '长沙', '郑州', '合肥', '福州', '昆明', '哈尔滨', '大连', '宁波', '无锡', '佛山', '东莞', '烟台', '珠海', '南昌', '徐州', '泰安', '德州', '曲阜')

router = APIRouter(prefix='/chat', tags=['chat'])
memory_store = RedisMemoryStore()
settings = get_settings()
_client = TencentWebServiceClient()
_TEXT_EXTENSIONS = {'.txt', '.md', '.csv', '.log', '.json'}
_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.webm', '.flac', '.opus', '.amr', '.3gp'}
_MAX_EXTRACT_CHARS = 4000




_LOCATION_PATTERNS = [
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
_CHINESE_NUMERAL_MAP = {
    '零': 0,
    '一': 1,
    '二': 2,
    '两': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
    '十': 10,
}


def _strip_common_noise(text: str) -> str:
    cleaned = text.strip()
    for phrase in _COMMON_PREFIXES:
        cleaned = cleaned.replace(phrase, '')
    for word in _TRAVEL_NOISE_WORDS:
        cleaned = cleaned.replace(word, '')
    cleaned = cleaned.strip('的').strip()
    return cleaned



def _clean_location(value: str) -> str:
    text = _strip_common_noise(value.strip().strip('，。；,！？ '))
    text = text.replace('从', '').replace('去', '').replace('到', '')
    text = text.replace('→', '').replace('->', '').replace('-->', '').strip()
    text = re.sub(r'进行为期.*$', '', text).strip()
    text = re.sub(r'的\d+\s*天.*$', '', text).strip()
    text = re.sub(r'\d+\s*天.*$', '', text).strip()
    text = _LOCATION_TRAILING_PATTERN.sub('', text).strip()
    text = text.strip('的').strip()
    for suffix in ('出发地', '目的地', '出发', '去', '到', '前往', '回到', '一带', '附近'):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or value.strip()



def _extract_locations(question: str) -> tuple[str | None, str | None]:
    text = question.strip()
    cleaned_text = _strip_common_noise(text)
    cleaned_text = _LOCATION_TRAILING_PATTERN.sub('', cleaned_text).strip()

    for pattern in _LOCATION_PATTERNS:
        match = re.search(pattern, cleaned_text)
        if match:
            origin = _clean_location(match.group('origin'))
            destination = _clean_location(match.group('destination'))
            if origin and destination:
                return origin, destination
    for separator in ('到', '去'):
        if separator in cleaned_text and len(cleaned_text.split(separator)) == 2:
            origin, destination = cleaned_text.split(separator, 1)
            origin = _clean_location(origin)
            destination = _clean_location(destination)
            if origin and destination:
                return origin, destination
    if '→' in cleaned_text and len(cleaned_text.split('→')) == 2:
        origin, destination = cleaned_text.split('→', 1)
        origin = _clean_location(origin)
        destination = _clean_location(destination)
        if origin and destination:
            return origin, destination
    return None, None


def _parse_chinese_number(text: str) -> int | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if cleaned in _CHINESE_NUMERAL_MAP:
        return _CHINESE_NUMERAL_MAP[cleaned]
    if cleaned == '十':
        return 10
    if cleaned.startswith('十') and len(cleaned) == 2:
        return 10 + _CHINESE_NUMERAL_MAP.get(cleaned[1], 0)
    if cleaned.endswith('十') and len(cleaned) == 2:
        return _CHINESE_NUMERAL_MAP.get(cleaned[0], 0) * 10
    if '十' in cleaned and len(cleaned) == 3:
        left, _, right = cleaned[0], cleaned[1], cleaned[2]
        return _CHINESE_NUMERAL_MAP.get(left, 0) * 10 + _CHINESE_NUMERAL_MAP.get(right, 0)
    return None



def _extract_trip_details(text: str | None) -> dict[str, str | None]:
    source = text or ''
    duration_match = re.search(r'(\d+)\s*天', source)
    chinese_duration_match = re.search(r'([一二两三四五六七八九十]+)\s*天', source)
    budget_match = re.search(r'预算\s*(\d+)|(?:总预算|花费|控制在)\s*(\d+)', source)
    nights_match = re.search(r'(\d+)\s*晚', source)
    chinese_nights_match = re.search(r'([一二两三四五六七八九十]+)\s*晚', source)
    duration_days = duration_match.group(1) if duration_match else None
    if not duration_days and chinese_duration_match:
        chinese_days = _parse_chinese_number(chinese_duration_match.group(1))
        duration_days = str(chinese_days) if chinese_days is not None else None
    nights = nights_match.group(1) if nights_match else None
    if not nights and chinese_nights_match:
        chinese_nights = _parse_chinese_number(chinese_nights_match.group(1))
        nights = str(chinese_nights) if chinese_nights is not None else None
    budget = None
    if budget_match:
        budget = budget_match.group(1) or budget_match.group(2)
    return {
        'duration_days': duration_days,
        'budget': budget,
        'nights': nights,
    }



def _extract_travel_mode(text: str | None, fallback: str | None = None) -> str:
    source = text or ''
    if any(keyword in source for keyword in ('公交', '地铁', '公共交通', '巴士', '大巴', '换乘')):
        return 'transit'
    if any(keyword in source for keyword in ('骑行', '单车', '自行车')):
        return 'bicycling'
    if any(keyword in source for keyword in ('步行', '走路', '徒步')):
        return 'walking'
    if any(keyword in source for keyword in ('自驾', '驾车', '开车', '租车')):
        return 'driving'
    return fallback or 'driving'



def _extract_interest_keywords(text: str | None) -> list[str]:
    source = text or ''
    patterns = [
        r'沿途(?:想看|想去|希望安排|顺路看)(?P<items>[^，。；,]+)',
        r'想看(?P<items>[^，。；,]+)',
        r'想去(?P<items>[^，。；,]+)',
        r'喜欢(?P<items>[^，。；,]+)',
        r'偏好(?P<items>[^，。；,]+)',
    ]
    stopwords = {'一下', '一个', '一些', '看看', '安排', '路线', '行程', '景点'}
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            items_text = match.group('items')
            for item in re.split(r'[和及、,，/\s]+', items_text):
                cleaned = item.strip('，。；,！？ ')
                cleaned = re.sub(r'^(看看|看|去|逛|安排)', '', cleaned).strip()
                cleaned = re.sub(r'(即可|就行|就好|为主)$', '', cleaned).strip()
                if not cleaned or len(cleaned) <= 1 or cleaned in stopwords:
                    continue
                if cleaned and cleaned not in found:
                    found.append(cleaned)
    return found[:6]



def _extract_weather_preferences(text: str | None) -> list[str]:
    source = text or ''
    preferences: list[str] = []
    mapping = {
        '避暑': '希望避暑，优先安排室内或清凉路线',
        '凉快': '偏好凉爽天气出行',
        '下雨': '希望兼顾雨天可执行方案',
        '雨天': '希望兼顾雨天可执行方案',
        '晴天': '偏好晴天观景路线',
        '高温': '尽量避开高温暴晒时段',
        '不想淋雨': '尽量避开降雨时段',
    }
    for keyword, description in mapping.items():
        if keyword in source and description not in preferences:
            preferences.append(description)
    return preferences



def _extract_question_waypoints(text: str | None) -> list[dict[str, str]]:
    source = text or ''
    patterns = [
        r'途经(?P<items>[^，。；,]+)',
        r'顺路去(?P<items>[^，。；,]+)',
        r'中途想去(?P<items>[^，。；,]+)',
    ]
    waypoints: list[dict[str, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            items_text = match.group('items')
            for item in re.split(r'[和及、,，/]+', items_text):
                cleaned = item.strip()
                cleaned = re.sub(r'(看|去|逛|经过)$', '', cleaned).strip()
                if not cleaned or len(cleaned) <= 1:
                    continue
                if not any(existing['name'] == cleaned for existing in waypoints):
                    waypoints.append({'name': cleaned})
    return waypoints[:5]


def _looks_like_general_chat(question: str) -> bool:
    cleaned = (question or '').strip()
    if not cleaned:
        return False
    lower_cleaned = cleaned.lower()
    general_markers = (
        '你好', '您好', '你是谁', '你是做什么的', '你能做什么', '介绍一下你自己', '在吗', '早上好', '晚上好',
        '解释', '说明', '翻译', '总结', '概括', '提取', '分析', '润色', '改写', '整理', '回答', '什么意思', '怎么理解', '为什么', '帮我看看', '帮我写', '帮我改',
        'hello', 'hi', 'help', 'what', 'why', 'translate', 'summarize', 'summary', 'explain', 'rewrite', 'polish',
    )
    travel_markers = (*_TRAVEL_NOISE_WORDS, '路线', '路书', '攻略', '怎么去', '怎么走', '出发', '目的地', '途经', '一日游', '两天一晚', '三天两晚', '附近', '周边', '酒店', '餐厅', '景点')
    if any(marker in lower_cleaned for marker in ('hello', 'hi', 'help', 'translate', 'summarize', 'summary', 'explain', 'rewrite', 'polish', 'what', 'why')):
        return True
    if any(marker in cleaned for marker in general_markers):
        return True
    if any(marker in cleaned for marker in travel_markers):
        return False
    return len(cleaned) <= 80



def _classify_chat_intent(question: str) -> str:
    if _looks_like_general_chat(question):
        return 'general_chat'
    parsed_origin, parsed_destination = _extract_locations(question)
    trip_details = _extract_trip_details(question)
    if any(keyword in question for keyword in NEARBY_KEYWORDS):
        return 'nearby_search'
    if parsed_origin and parsed_destination:
        return 'travel_planning'
    if any(trip_details.values()):
        return 'travel_planning'
    if any(keyword in question for keyword in (*_TRAVEL_NOISE_WORDS, '路线', '路书', '攻略', '怎么去', '怎么走', '出发', '目的地', '途经', '一日游', '两天一晚', '三天两晚')):
        return 'travel_planning'
    return 'general_chat'



def _build_general_response(request: ChatRequest) -> dict:
    return {
        'conversation_id': request.conversation_id or 'default',
        'answer_type': 'general_chat',
        'final_answer': '',
        'data': {},
        'travel_request': None,
        'upload_context': None,
        'meta': {'source': 'llm_general_chat'},
        'error': None,
    }



async def _generate_general_answer(question: str, conversation_id: str) -> str:
    if not settings.qwen_api_key:
        return '你好，我是你的旅行助手，也可以帮你回答普通问题。'

    context = memory_store.get_context(conversation_id)
    short_term = context.get('short_term', []) if isinstance(context, dict) else []
    history_lines: list[str] = []
    for turn in short_term[-6:]:
        if not isinstance(turn, dict):
            continue
        user_text = str(turn.get('user_input') or turn.get('user') or '').strip()
        assistant_text = str(turn.get('assistant_output') or turn.get('assistant') or '').strip()
        if user_text:
            history_lines.append(f'用户：{user_text}')
        if assistant_text:
            history_lines.append(f'助手：{assistant_text}')
    history_text = '\n'.join(history_lines) if history_lines else '无'
    system_prompt = (
        '你是一个中文旅行与生活助理。'
        '如果用户的问题与旅行无关，也要直接、简洁、自然地回答，不要硬转成旅游规划。'
        '你还需要处理通用的大模型任务，例如解释、翻译、总结、概括、提取要点、改写、润色、分析和普通闲聊。'
        '如果用户在问“你好你是谁”这类问题，就直接介绍自己的身份即可。'
    )
    payload = {
        'model': settings.qwen_model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'历史对话：\n{history_text}\n\n当前问题：{question}\n\n请直接用中文回答。'},
        ],
        'temperature': 0.7,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.qwen_api_base.rstrip('/')}/chat/completions",
                headers={
                    'Authorization': f'Bearer {settings.qwen_api_key}',
                    'Content-Type': 'application/json',
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
        choices = result.get('choices') if isinstance(result, dict) else None
        if isinstance(choices, list) and choices:
            message = choices[0].get('message', {}) if isinstance(choices[0], dict) else {}
            content = message.get('content') if isinstance(message, dict) else ''
            if isinstance(content, str) and content.strip():
                return content.strip()
    except Exception:
        pass
    return '你好，我是你的旅行助手，也可以帮你回答普通问题。'



def _looks_like_direct_file_question(text: str) -> bool:
    cleaned = _strip_common_noise(text)
    if not cleaned:
        return False
    question_markers = ('什么', '为什么', '怎么', '如何', '多少', '谁', '哪', '几', '是', '在', '吗', '呢', '吧', '请回答', '解释', '总结', '概括', '翻译', '提取')
    travel_markers = ('路线', '行程', '旅游', '景点', '酒店', '餐厅', '周边', '出发地', '目的地', '攻略')
    return any(marker in cleaned for marker in question_markers) and not any(marker in cleaned for marker in travel_markers)



def _build_file_answer_prompt(file_context: dict, question: str | None = None) -> str:
    extracted_text = str(file_context.get('extracted_text') or '').strip()
    if extracted_text:
        return extracted_text
    if question and question.strip():
        return question.strip()
    return str(file_context.get('extraction_error') or '').strip()



def _build_preference_summary(question: str, existing_preferences: str | None, travel_mode: str, trip_details: dict[str, str | None]) -> str:
    parts: list[str] = []
    mode_labels = {
        'driving': '自驾/驾车',
        'walking': '步行',
        'transit': '公共交通',
        'bicycling': '骑行',
    }
    parts.append(f'出行方式：{mode_labels.get(travel_mode, travel_mode)}')
    if trip_details.get('budget'):
        parts.append(f'预算：{trip_details["budget"]}元')
    if trip_details.get('duration_days'):
        parts.append(f'行程时长：{trip_details["duration_days"]}天')
    if trip_details.get('nights'):
        parts.append(f'住宿节奏：{trip_details["nights"]}晚')
    interest_keywords = _extract_interest_keywords(question)
    if interest_keywords:
        parts.append(f'沿途偏好：{"、".join(interest_keywords)}')
    weather_preferences = _extract_weather_preferences(question)
    parts.extend(weather_preferences)
    if any(word in question for word in ('老人', '长辈')):
        parts.append('同行人群：有老人，行程节奏宜放缓')
    if any(word in question for word in ('孩子', '亲子', '小朋友')):
        parts.append('同行人群：亲子出行，优先互动性景点')
    if any(word in question for word in ('美食', '小吃', '餐厅')):
        parts.append('游玩偏好：希望加入美食安排')
    if existing_preferences and existing_preferences.strip():
        raw_preferences = re.split(r'[；;\n]+', existing_preferences.strip())
        for item in raw_preferences:
            cleaned = item.strip()
            if not cleaned:
                continue
            if cleaned.startswith('出行方式：') or cleaned.startswith('预算：') or cleaned.startswith('行程时长：') or cleaned.startswith('住宿节奏：'):
                continue
            parts.append(cleaned)
    deduped: list[str] = []
    for item in parts:
        if item and item not in deduped:
            deduped.append(item)
    return '；'.join(deduped)



def _parse_waypoints(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    waypoints: list[dict[str, str]] = []
    for item in parsed:
        if isinstance(item, dict) and item.get('name'):
            waypoints.append({'name': str(item['name']).strip()})
    return [item for item in waypoints if item['name']]


def _truncate_text(text: str, limit: int = _MAX_EXTRACT_CHARS) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return f'{compact[:limit]}…'



def _normalize_extracted_text(text: str) -> str:
    lines: list[str] = []
    previous = ''
    for raw_line in text.splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line:
            if lines and lines[-1] != '':
                lines.append('')
            continue
        if line == previous:
            continue
        if len(line) <= 2 and previous and previous.endswith(line):
            continue
        lines.append(line)
        previous = line
    normalized = '\n'.join(lines)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    return _truncate_text(normalized)



def _looks_like_pdf_scan(content: bytes) -> bool:
    if b'/Font' in content or b'/Text' in content:
        return False
    return content.count(b'\x00') < max(20, len(content) // 50)



def _extract_text_from_pdf(content: bytes) -> str:
    extracted_parts: list[str] = []
    try:
        reader = PdfReader(BytesIO(content))
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ''
            except Exception:
                page_text = ''
            if page_text.strip():
                extracted_parts.append(page_text)
    except Exception:
        extracted_parts = []

    text = '\n'.join(extracted_parts).strip()
    if text:
        return _normalize_extracted_text(text)

    if _looks_like_pdf_scan(content):
        debug_hint = 'scanned_pdf_without_text_layer'
        return ''
    return ''



def _decode_plain_bytes(content: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5', 'latin-1'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ''



def _extract_text_from_plain_file(content: bytes) -> str:
    decoded = _decode_plain_bytes(content)
    if not decoded:
        return ''
    decoded = decoded.replace('\r\n', '\n').replace('\r', '\n')
    decoded = re.sub(r'\u0000+', '', decoded)
    decoded = re.sub(r'(?m)^[\s\-_=\*#]{3,}$', '', decoded)
    decoded = re.sub(r'(?m)^\s*\d+\s*$', '', decoded)
    return _normalize_extracted_text(decoded)


def _ffmpeg_binary() -> str:
    configured = getattr(settings, 'ffmpeg_path', '') or ''
    if configured and Path(configured).exists():
        return configured
    common_candidates = [
        Path(r'D:\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'),
        Path(r'D:\ffmpeg\bin\ffmpeg.exe'),
        Path(r'C:\ffmpeg\bin\ffmpeg.exe'),
    ]
    for candidate in common_candidates:
        if candidate.exists():
            return str(candidate)
    return 'ffmpeg'


def _convert_audio_to_wav(content: bytes, suffix: str) -> bytes:
    source_suffix = suffix or '.wav'
    temp_dir = Path(tempfile.mkdtemp(prefix='travel_agent_audio_'))
    input_path = temp_dir / f'input{source_suffix}'
    output_path = temp_dir / 'output.wav'
    input_path.write_bytes(content)
    try:
        import subprocess
        ffmpeg_bin = _ffmpeg_binary()
        cmd = [
            ffmpeg_bin,
            '-y',
            '-i', str(input_path),
            '-ac', '1',
            '-ar', '16000',
            '-f', 'wav',
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        if output_path.exists():
            return output_path.read_bytes()
        return content
    except Exception:
        return content
    finally:
        try:
            if input_path.exists():
                input_path.unlink(missing_ok=True)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            pass


def _transcribe_audio(filename: str, content: bytes, content_type: str | None) -> tuple[str, str, dict]:
    debug: dict = {}
    if not settings.qwen_api_key:
        debug['stage'] = 'missing_api_key'
        return '', 'missing_api_key', debug

    suffix = Path(filename or 'audio').suffix.lower() or '.mp3'
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(content)
    temp_file.flush()
    temp_file.close()
    temp_path = Path(temp_file.name)
    wav_path: Path | None = None
    pcm_path: Path | None = None

    try:
        debug['input_suffix'] = suffix
        debug['content_type'] = content_type or mimetypes.guess_type(filename or temp_path.name)[0] or 'audio/mpeg'
        with temp_path.open('rb') as audio_file:
            audio_bytes = audio_file.read()
        debug['input_size'] = len(audio_bytes)

        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        wav_file.close()
        wav_path = Path(wav_file.name)
        pcm_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pcm')
        pcm_file.close()
        pcm_path = Path(pcm_file.name)

        try:
            import subprocess
            ffmpeg_bin = _ffmpeg_binary()
            wav_cmd = [
                ffmpeg_bin,
                '-y',
                '-i', str(temp_path),
                '-ac', '1',
                '-ar', str(settings.fun_asr_sample_rate),
                '-f', 'wav',
                str(wav_path),
            ]
            subprocess.run(wav_cmd, check=True, capture_output=True)
            pcm_cmd = [
                ffmpeg_bin,
                '-y',
                '-i', str(wav_path),
                '-ac', '1',
                '-ar', str(settings.fun_asr_sample_rate),
                '-f', 's16le',
                '-acodec', 'pcm_s16le',
                str(pcm_path),
            ]
            subprocess.run(pcm_cmd, check=True, capture_output=True)
        except Exception as exc:
            debug['error_type'] = exc.__class__.__name__
            debug['error_message'] = f'pcm_convert_failed: {exc}'
            return '', f'pcm_convert_failed: {exc}', debug

        pcm_bytes = pcm_path.read_bytes() if pcm_path.exists() else b''
        debug['converted_size'] = len(pcm_bytes)
        if not pcm_bytes:
            debug['error_type'] = 'PCMConversionError'
            debug['error_message'] = 'empty_pcm_output'
            return '', 'empty_pcm_output', debug

        workspace_id = settings.dashscope_workspace_id.strip()
        if not workspace_id:
            debug['stage'] = 'missing_workspace_id'
            return '', 'missing_workspace_id', debug

        ws_url = f'wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime'
        debug['ws_url'] = ws_url

        event_counter = 0
        def next_event_id() -> str:
            nonlocal event_counter
            event_counter += 1
            return f'event_{event_counter}'

        session_update = {
            'event_id': next_event_id(),
            'type': 'session.update',
            'session': {
                'input_audio_format': 'pcm',
                'sample_rate': settings.fun_asr_sample_rate,
                'input_audio_transcription': {
                    'language': settings.fun_asr_language_hint,
                },
                'turn_detection': None,
            },
        }
        input_append_template = {
            'event_id': '',
            'type': 'input_audio_buffer.append',
            'audio': '',
        }
        input_commit = {
            'event_id': next_event_id(),
            'type': 'input_audio_buffer.commit',
        }
        session_finish = {
            'event_id': next_event_id(),
            'type': 'session.finish',
        }

        headers = [f'Authorization: Bearer {settings.qwen_api_key}', f'X-DashScope-WorkSpace: {workspace_id}']
        ws = websocket.create_connection(ws_url, header=headers, timeout=30)
        try:
            ws.send(json.dumps(session_update, ensure_ascii=False))
            debug['sent_session_update'] = True
            transcript_parts: list[str] = []
            audio_sent = False
            chunk_size = 3200
            session_updated_seen = False

            while True:
                raw_message = ws.recv()
                if raw_message is None:
                    break
                debug.setdefault('events', []).append(raw_message)
                try:
                    event_payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                event_type = event_payload.get('type') if isinstance(event_payload, dict) else None
                if event_type == 'session.updated' and not audio_sent:
                    session_updated_seen = True
                    for index in range(0, len(pcm_bytes), chunk_size):
                        chunk = pcm_bytes[index:index + chunk_size]
                        if chunk:
                            append_msg = dict(input_append_template)
                            append_msg['event_id'] = next_event_id()
                            append_msg['audio'] = base64.b64encode(chunk).decode('utf-8')
                            ws.send(json.dumps(append_msg, ensure_ascii=False))
                    debug['sent_audio_bytes'] = len(pcm_bytes)
                    audio_sent = True
                    ws.send(json.dumps(input_commit, ensure_ascii=False))
                    debug['sent_input_commit'] = True
                    ws.send(json.dumps(session_finish, ensure_ascii=False))
                    debug['sent_session_finish'] = True
                elif event_type == 'conversation.item.input_audio_transcription.text':
                    text = str(event_payload.get('text') or '').strip() if isinstance(event_payload, dict) else ''
                    stash = str(event_payload.get('stash') or '').strip() if isinstance(event_payload, dict) else ''
                    preview = f'{text}{stash}'.strip()
                    if preview:
                        transcript_parts.append(preview)
                        debug['transcript_preview'] = _truncate_text(''.join(transcript_parts))
                elif event_type == 'conversation.item.input_audio_transcription.completed':
                    transcript = str(event_payload.get('transcript') or '').strip() if isinstance(event_payload, dict) else ''
                    if transcript:
                        transcript_parts.append(transcript)
                        debug['transcript_preview'] = _truncate_text(''.join(transcript_parts))
                elif event_type == 'session.finished':
                    break
                elif event_type == 'error':
                    error_obj = event_payload.get('error', {}) if isinstance(event_payload, dict) else {}
                    debug['error_type'] = str(error_obj.get('type') or 'error')
                    debug['error_message'] = str(error_obj.get('message') or 'task failed')
                    return '', f"{debug['error_type']}: {debug['error_message']}", debug
            if transcript_parts:
                transcript = _truncate_text(''.join(transcript_parts))
                debug['result_type'] = 'transcription.completed'
                debug['response_keys'] = ['type', 'event_id']
                debug['session_updated_seen'] = session_updated_seen
                return transcript, '', debug
            debug['error_type'] = 'RecognitionError'
            debug['error_message'] = 'empty_transcription_response'
            return '', 'empty_transcription_response', debug
        finally:
            try:
                ws.close()
            except Exception:
                pass
    except Exception as exc:
        debug['error_type'] = exc.__class__.__name__
        debug['error_message'] = str(exc)
        return '', f'{exc.__class__.__name__}: {exc}', debug
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        if pcm_path is not None:
            try:
                pcm_path.unlink(missing_ok=True)
            except OSError:
                pass


def _extract_upload_context(upload: UploadFile | None, content: bytes | None) -> dict | None:
    if upload is None or content is None:
        return None
    filename = upload.filename or 'uploaded-file'
    suffix = Path(filename).suffix.lower()
    content_type = upload.content_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    extracted_text = ''
    file_kind = 'binary'
    extraction_error = ''
    audio_debug: dict = {}

    if content_type.startswith('image/'):
        file_kind = 'image'
    elif suffix == '.pdf' or content_type == 'application/pdf':
        file_kind = 'pdf'
        try:
            extracted_text = _extract_text_from_pdf(content)
        except Exception as exc:
            extraction_error = f'pdf_extract_failed: {exc}'
    elif suffix in _TEXT_EXTENSIONS or content_type.startswith('text/'):
        file_kind = 'text'
        try:
            extracted_text = _extract_text_from_plain_file(content)
        except Exception as exc:
            extraction_error = f'text_extract_failed: {exc}'
    elif suffix in _AUDIO_EXTENSIONS or content_type.startswith('audio/'):
        file_kind = 'audio'
        extracted_text, audio_error, audio_debug = _transcribe_audio(filename, content, content_type)
        if not extracted_text:
            extraction_error = audio_error or 'audio_transcribe_failed'

    upload_context = {
        'filename': filename,
        'content_type': content_type,
        'size': len(content),
        'file_kind': file_kind,
        'extracted_text': extracted_text,
        'extraction_error': extraction_error,
    }
    if audio_debug:
        upload_context['audio_debug'] = audio_debug
    return upload_context


def _merge_question_with_file_context(question: str, file_context: dict | None) -> str:
    if not file_context:
        return question
    extracted_text = str(file_context.get('extracted_text') or '').strip()
    if extracted_text:
        return extracted_text
    error_text = str(file_context.get('extraction_error') or '').strip()
    return question if question.strip() else error_text


def _build_travel_request(request: ChatRequest) -> TravelPlanRequest:
    parsed_origin, parsed_destination = _extract_locations(request.question)
    trip_details = _extract_trip_details(request.question)
    travel_mode = _extract_travel_mode(request.question, request.travel_mode)
    if parsed_origin and parsed_destination:
        origin = parsed_origin
        destination = parsed_destination
    else:
        origin = (request.origin or '').strip()
        destination = (request.destination or '').strip()
        if origin and origin not in request.question and parsed_origin is None:
            origin = ''
        if destination and destination not in request.question and parsed_destination is None:
            destination = ''
        origin = origin or parsed_origin or '起点'
        destination = destination or parsed_destination or '终点'
    source_query = request.question
    if parsed_origin and parsed_destination:
        source_query = f'{parsed_origin}到{parsed_destination} | 天数:{trip_details["duration_days"] or "未知"} | 预算:{trip_details["budget"] or "未知"} | 原始输入:{request.question}'
    preference_text = (request.preferences or '').strip()
    question_text = request.question or ''
    merged_preference_text = '；'.join(part for part in [preference_text, question_text] if part)
    trip_profile = {
        'duration_days': int(trip_details['duration_days']) if trip_details['duration_days'] else None,
        'budget': trip_details['budget'],
        'travel_style': '轻松慢游' if any(word in merged_preference_text for word in ('轻松', '慢游', '休闲', '不赶')) else '常规游玩',
        'companions': '家庭/朋友' if any(word in merged_preference_text for word in ('家人', '家庭', '朋友', '亲子')) else '默认',
    }
    resolved_preferences = _build_preference_summary(question_text, preference_text, travel_mode, trip_details)
    explicit_waypoints = _parse_waypoints(request.waypoints_json)
    inferred_waypoints = _extract_question_waypoints(question_text)
    merged_waypoints: list[dict[str, str]] = []
    for item in [*explicit_waypoints, *inferred_waypoints]:
        name = str(item.get('name', '')).strip()
        if name and not any(existing['name'] == name for existing in merged_waypoints):
            merged_waypoints.append({'name': name})
    return TravelPlanRequest(
        origin=origin,
        destination=destination,
        travel_mode=travel_mode,  # type: ignore[arg-type]
        preferences=resolved_preferences,
        source_query=source_query,
        conversation_id=request.conversation_id,
        waypoints=merged_waypoints,
        waypoint_order=bool(request.waypoint_order) if request.waypoint_order is not None else False,
        request_source='chat',
        trip_profile=trip_profile,
    )


_POI_BLOCKED_NAME_HINTS = (
    '本地生活', '服务中心', '营销中心', '售楼处', '写字楼', '商务中心', '公寓', '住宅', '小区', '家电', '银行', '公司', '中心店', '旗舰店', '专卖店', '便利店', '超市',
)

_POI_BLOCKED_CATEGORY_HINTS = (
    '房地产', '公司企业', '生活服务', '购物', '金融', '汽车服务', '房产小区', '商务住宅',
)

_SCENIC_ALLOWED_HINTS = (
    '景区', '风景区', '名胜', '古迹', '古镇', '古城', '城墙', '博物馆', '纪念馆', '美术馆', '科技馆', '文化馆', '公园', '湿地', '乐园', '寺', '塔', '湖', '山', '步道', '遗址', '街区',
)

_FOOD_ALLOWED_HINTS = (
    '餐厅', '饭店', '小吃', '面馆', '火锅', '烧烤', '咖啡', '茶馆', '酒楼', '美食', '甜品', '早餐', '夜宵',
)

_HOTEL_ALLOWED_HINTS = (
    '酒店', '宾馆', '民宿', '客栈', '旅舍', '公寓酒店', '度假酒店',
)


def _poi_matches_bucket(item: dict[str, str], keyword: str) -> bool:
    name = item.get('name', '')
    category = item.get('category', '')
    combined = f'{name} {category}'
    if any(token in combined for token in _POI_BLOCKED_NAME_HINTS):
        return False
    if any(token in category for token in _POI_BLOCKED_CATEGORY_HINTS):
        return False
    if keyword == '景点':
        return any(token in combined for token in _SCENIC_ALLOWED_HINTS)
    if keyword == '餐厅':
        return any(token in combined for token in _FOOD_ALLOWED_HINTS)
    if keyword == '酒店':
        return any(token in combined for token in _HOTEL_ALLOWED_HINTS)
    return True



def _extract_poi_list(payload: dict | None, limit: int = 8, keyword: str | None = None) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get('data') or payload.get('result') or []
    if isinstance(candidates, dict):
        candidates = [candidates]
    elif not isinstance(candidates, list):
        candidates = []
    results: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get('title') or item.get('name') or '').strip()
        if not name:
            continue
        address = str(item.get('address') or '').strip()
        category = str(item.get('category') or '').strip()
        location = item.get('location') if isinstance(item.get('location'), dict) else {}
        lat = location.get('lat')
        lng = location.get('lng')
        coords = f'{lat},{lng}' if lat is not None and lng is not None else ''
        poi_id = str(item.get('id') or item.get('uid') or '').strip()
        poi = {'id': poi_id, 'name': name, 'address': address, 'category': category, 'location': coords}
        results.append(poi)
    return results[:limit]


def _extract_location_point(payload: dict | None) -> tuple[str | None, dict[str, object]]:
    debug: dict[str, object] = {'source': None, 'raw': payload}
    if not isinstance(payload, dict):
        return None, debug
    result = payload.get('result') if isinstance(payload.get('result'), dict) else payload
    if not isinstance(result, dict):
        return None, debug
    debug['result'] = result
    location = result.get('location') if isinstance(result.get('location'), dict) else {}
    if isinstance(location, dict):
        lat = location.get('lat')
        lng = location.get('lng')
        if lat is not None and lng is not None:
            debug['source'] = 'location'
            return f'{lat},{lng}', debug
    poi_location = result.get('location') if isinstance(result.get('location'), dict) else None
    if isinstance(poi_location, dict):
        lat = poi_location.get('lat')
        lng = poi_location.get('lng')
        if lat is not None and lng is not None:
            debug['source'] = 'poi_location'
            return f'{lat},{lng}', debug
    return None, debug


def _resolve_nearby_anchor(question: str, city: str, forced_anchor: str | None = None) -> tuple[str, str | None, dict[str, object]]:
    anchor = _normalize_anchor_candidate((forced_anchor or _extract_nearby_anchor_text(question) or city).strip()) or city
    if anchor == '目标城市':
        origin, destination = _extract_locations(question)
        anchor = destination or origin or city
    point: str | None = None
    debug: dict[str, object] = {'anchor': anchor, 'mode': None, 'attempts': []}
    if settings.tencent_maps_key:
        try:
            anchor_payload = _client.suggestion(anchor, region=city)
            point, point_debug = _extract_location_point(anchor_payload)
            debug['attempts'].append({'type': 'suggestion', 'debug': point_debug})
            if point:
                debug['mode'] = 'poi'
                return anchor, point, debug
        except Exception as exc:
            debug['attempts'].append({'type': 'suggestion', 'error': str(exc)})
        try:
            geocoder = _client.smart_geocoder(anchor, region=city)
            point, point_debug = _extract_location_point(geocoder)
            debug['attempts'].append({'type': 'geocoder', 'debug': point_debug})
            if point:
                debug['mode'] = 'address'
                return anchor, point, debug
        except Exception as exc:
            debug['attempts'].append({'type': 'geocoder', 'error': str(exc)})
        try:
            place_payload = _client.place_search_by_region(anchor, city, page_size=5, page_index=1)
            raw_place_items = _extract_poi_list(place_payload, 5)
            place_items = [item for item in raw_place_items if _poi_matches_bucket(item, '景点')]
            debug['attempts'].append({'type': 'place_search', 'raw_count': len(raw_place_items), 'count': len(place_items)})
            if place_items:
                first = place_items[0]
                if first.get('location'):
                    debug['mode'] = 'landmark'
                    return anchor, first['location'], debug
        except Exception as exc:
            debug['attempts'].append({'type': 'place_search', 'error': str(exc)})
    debug['mode'] = 'city_fallback'
    return anchor, None, debug


def _search_nearby_category(keyword: str, anchor: str, anchor_point: str | None, city: str, radius: int = 1500) -> tuple[list[dict[str, str]], dict[str, object]]:
    debug: dict[str, object] = {'keyword': keyword, 'anchor': anchor, 'anchor_point': anchor_point, 'city': city, 'radius_candidates': []}
    if not settings.tencent_maps_key:
        debug['reason'] = 'missing_key'
        return [], debug

    collected: list[dict[str, str]] = []
    query_terms = [keyword]
    if keyword == '酒店':
        query_terms += ['宾馆', '民宿', '度假酒店']
    elif keyword == '餐厅':
        query_terms += ['美食', '小吃', '本地菜', '特色餐', '饭店']
    elif keyword == '景点':
        query_terms += ['公园', '博物馆', '地标', '商场']

    regions: list[tuple[str, str | None]] = []
    if anchor_point:
        regions.append((anchor, anchor_point))
    regions.append((city, None))

    radius_candidates = [radius, max(radius * 2, 2500), max(radius * 3, 4000)]
    debug['radius_candidates'] = radius_candidates
    seen_keys: set[str] = set()
    round_debug: list[dict[str, object]] = []

    for current_city, current_point in regions:
        for current_radius in radius_candidates:
            for term in query_terms:
                attempt: dict[str, object] = {'term': term, 'current_city': current_city, 'current_point': current_point, 'radius': current_radius}
                try:
                    if current_point:
                        payload = _client.place_search_nearby_sorted(term, current_point, radius=current_radius, page_size=10, page_index=1)
                    else:
                        payload = _client.place_search_by_region(term, current_city, page_size=10, page_index=1)
                    attempt['payload'] = payload
                    raw_items = _extract_poi_list(payload, 10)
                    items = [item for item in raw_items if _poi_matches_bucket(item, keyword)] if keyword else raw_items
                    attempt['raw_item_count'] = len(raw_items)
                    attempt['item_count'] = len(items)
                except Exception as exc:
                    attempt['error'] = str(exc)
                    round_debug.append(attempt)
                    continue

                for item in items:
                    key = f"{item.get('name', '')}|{item.get('address', '')}|{item.get('location', '')}"
                    if not item.get('address') and item.get('id'):
                        try:
                            detail = _client.place_detail(item['id'])
                            attempt.setdefault('details', []).append(detail)
                            detail_result = detail.get('data') or detail.get('result') or {}
                            if isinstance(detail_result, dict):
                                address = str(detail_result.get('address') or detail_result.get('ad_info', {}).get('name') or '').strip()
                                if address:
                                    item['address'] = address
                                loc = detail_result.get('location') if isinstance(detail_result.get('location'), dict) else {}
                                lat = loc.get('lat')
                                lng = loc.get('lng')
                                if lat is not None and lng is not None:
                                    item['location'] = f'{lat},{lng}'
                                key = f"{item.get('name', '')}|{item.get('address', '')}|{item.get('location', '')}"
                        except Exception as exc:
                            attempt.setdefault('detail_errors', []).append(str(exc))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    collected.append(item)
                    if len(collected) >= 12:
                        attempt['collected_total'] = len(collected)
                        round_debug.append(attempt)
                        debug['rounds'] = round_debug
                        debug['final_total'] = len(collected)
                        return collected, debug
                round_debug.append(attempt)

    debug['rounds'] = round_debug
    debug['final_total'] = len(collected)
    return collected, debug


def _normalize_anchor_candidate(value: str) -> str:
    anchor = value.strip('，。；,！？:： ').strip()
    anchor = re.sub(r'^(帮我|请|请帮我|推荐|查一下|查查|找一下|找找|看看|想找|我想找|我想看|推荐下)', '', anchor).strip()
    anchor = re.sub(r'(附近|周边|周围|旁边|临近|靠近)$', '', anchor).strip()
    anchor = re.sub(r'^(的|在|去|到)', '', anchor).strip()
    anchor = re.sub(r'(酒店|餐厅|景点|美食|商场|公园|博物馆|民宿|宾馆|饭店)+$', '', anchor).strip('的')
    return anchor.strip()



def _extract_nearby_anchor_text(question: str) -> str | None:
    patterns = [
        r'(?P<anchor>[^，。；,、/\s]{2,24})(?:附近|周边|周围|旁边|临近|靠近)',
        r'(?:附近|周边|周围|旁边|临近|靠近)(?:的)?(?P<anchor>[^，。；,、/\s]{2,24})',
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        anchor = _normalize_anchor_candidate(match.group('anchor'))
        if anchor:
            return anchor
    return None



def _resolve_query_city(request: ChatRequest) -> str:
    parsed_origin, parsed_destination = _extract_locations(request.question)
    if parsed_destination:
        return parsed_destination
    if parsed_origin and any(keyword in request.question for keyword in ('天气', '气温', '下雨', '降雨', '穿搭')):
        return parsed_origin
    current_anchor = _extract_nearby_anchor_text(request.question)
    if current_anchor:
        return current_anchor
    if request.force_current_anchor:
        return '目标城市'
    destination = (request.destination or '').strip()
    if destination and destination in request.question:
        return destination
    if destination:
        return destination
    origin = (request.origin or '').strip()
    if origin and origin in request.question:
        return origin
    if origin:
        return origin
    return '目标城市'


def _search_nearby_bucket(anchor: str, anchor_point: str | None, city: str, keyword: str, fallback_radius: int) -> tuple[list[dict[str, str]], dict[str, object]]:
    primary_items, primary_debug = _search_nearby_category(keyword, anchor, anchor_point, city, radius=1500)
    merged = list(primary_items)
    bucket_debug: dict[str, object] = {'primary': primary_debug, 'secondary': [], 'final_count': len(primary_items)}

    secondary_anchor_points: list[str | None] = []
    if anchor_point:
        secondary_anchor_points.append(anchor_point)
    if primary_items:
        secondary_anchor_points.extend(item.get('location') or None for item in primary_items[:3])
    secondary_anchor_points.append(None)

    seen = {f"{item.get('name','')}|{item.get('address','')}|{item.get('location','')}" for item in merged}
    for candidate_point in secondary_anchor_points:
        if len(merged) >= 8:
            break
        extra_items, extra_debug = _search_nearby_category(keyword, anchor, candidate_point, city, radius=fallback_radius)
        bucket_debug['secondary'].append(extra_debug)
        for item in extra_items:
            key = f"{item.get('name','')}|{item.get('address','')}|{item.get('location','')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= 8:
                break

    bucket_debug['final_count'] = len(merged)
    return merged[:8], bucket_debug



def _build_nearby_response(request: ChatRequest) -> dict:
    travel_request = _build_travel_request(request)
    forced_anchor = _extract_nearby_anchor_text(request.question)
    city = forced_anchor or _resolve_query_city(request)
    anchor, anchor_point, anchor_debug = _resolve_nearby_anchor(request.question, city, forced_anchor)
    attraction_recommendations: list[str] = []
    hotel_candidates: list[dict[str, str]] = []
    food_candidates: list[dict[str, str]] = []
    pois: list[dict[str, str]] = []
    debug: dict[str, object] = {
        'city': city,
        'anchor': anchor,
        'anchor_point': anchor_point,
        'anchor_debug': anchor_debug,
        'force_current_anchor': bool(request.force_current_anchor),
        'forced_anchor': forced_anchor,
    }
    try:
        hotel_candidates, hotel_debug = _search_nearby_bucket(anchor, anchor_point, city, '酒店', 3000)
        food_candidates, food_debug = _search_nearby_bucket(anchor, anchor_point, city, '餐厅', 2800)
        pois, poi_debug = _search_nearby_bucket(anchor, anchor_point, city, '景点', 3500)
        debug['hotel_debug'] = hotel_debug
        debug['food_debug'] = food_debug
        debug['poi_debug'] = poi_debug

        attraction_recommendations = []
        for item in pois:
            label = item['name']
            if item.get('address'):
                label = f"{label}（{item['address']}）"
            attraction_recommendations.append(label)
    except Exception as exc:
        debug['search_error'] = str(exc)
        attraction_recommendations = []
        pois = []
    attraction_recommendations = attraction_recommendations or []
    transportation_suggestion = []
    debug['hotel_count'] = len(hotel_candidates)
    debug['food_count'] = len(food_candidates)
    debug['poi_count'] = len(pois)
    hotel_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in hotel_candidates[:3]
        if item.get('name')
    )
    food_preview = '；'.join(
        f"{item.get('name')}{f'（{item.get('address')}）' if item.get('address') else ''}"
        for item in food_candidates[:3]
        if item.get('name')
    )
    poi_preview = '；'.join(attraction_recommendations[:4])
    final_answer_parts = [
        f'酒店：{hotel_preview}' if hotel_preview else '酒店：没有',
        f'餐厅：{food_preview}' if food_preview else '餐厅：没有',
        f'景点：{poi_preview}' if poi_preview else '景点：没有',
    ]
    return {
        'conversation_id': request.conversation_id or 'default',
        'answer_type': 'nearby_search',
        'final_answer': '\n'.join(final_answer_parts),
        'data': {
            'nearby': {
                'city': city,
                'anchor': anchor,
                'anchor_point': anchor_point,
                'anchor_debug': anchor_debug,
                'destination_point': anchor_point,
                'attraction_recommendations': attraction_recommendations,
                'transportation_suggestion': transportation_suggestion,
                'hotel_candidates': hotel_candidates,
                'food_candidates': food_candidates,
                'debug': debug,
            }
        },
        'travel_request': travel_request.model_dump(),
        'upload_context': None,
        'meta': {'source': 'poi_search', 'debug': debug},
        'error': None,
    }


@router.post('')
async def chat(request: ChatRequest) -> dict:
    conversation_id = request.conversation_id or 'default'
    memory_store.get_context(conversation_id)
    travel_request = _build_travel_request(request)
    intent = _classify_chat_intent(request.question)
    try:
        if intent == 'general_chat':
            response = _build_general_response(request)
            response['final_answer'] = await _generate_general_answer(request.question, conversation_id)
        else:
            graph_result = await asyncio.wait_for(unified_graph.ainvoke({'request': request}), timeout=45)
            response = graph_result.get('response') or _build_general_response(request)
            if response.get('answer_type') == 'travel_planning' and response.get('travel_request') is None:
                response['travel_request'] = travel_request.model_dump()
            if intent == 'general_chat' or (_looks_like_general_chat(request.question) and response.get('answer_type') == 'travel_planning'):
                response = _build_general_response(request)
                response['final_answer'] = await _generate_general_answer(request.question, conversation_id)
    except asyncio.TimeoutError:
        response = _build_general_response(request)
        response['final_answer'] = '请求处理超时：后端 Agent 在限定时间内没有返回结果，请检查地图/模型接口配置或稍后重试。'
        response['error'] = 'graph_timeout'
    except Exception as exc:
        response = _build_general_response(request)
        response['final_answer'] = f'请求处理失败：{exc}'
        response['error'] = str(exc)
    memory_store.append_turn(conversation_id, request.question, response['final_answer'])
    memory_store.update_profile(conversation_id, {'last_question': request.question, 'intent': intent, 'last_upload': None})
    return response


@router.get('')
def chat_health() -> dict[str, str]:
    return {'status': 'ok'}


@router.post('/multimodal')
async def multimodal_chat(
    question: str = Form(...),
    conversation_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    origin: str | None = Form(None),
    destination: str | None = Form(None),
    preferences: str | None = Form(None),
    travel_mode: str | None = Form(None),
    waypoint_order: str | None = Form(None),
    waypoints_json: str | None = Form(None),
) -> dict:
    conversation_id = conversation_id or 'default'
    memory_store.get_context(conversation_id)
    upload_context = None
    merged_question = question
    request_payload = ChatRequest(
        question=merged_question,
        conversation_id=conversation_id,
        image_context=None,
        origin=origin,
        destination=destination,
        preferences=preferences,
        travel_mode=travel_mode,
        waypoint_order=str(waypoint_order).lower() == 'true' if waypoint_order is not None else None,
        waypoints_json=waypoints_json,
        force_current_anchor=True,
    )
    upload_file = audio or image
    if upload_file is not None:
        content = await upload_file.read()
        upload_context = _extract_upload_context(upload_file, content)
        if upload_context.get('file_kind') == 'audio' and not str(upload_context.get('extracted_text') or '').strip():
            response = _build_general_response(request_payload)
            response['upload_context'] = upload_context
            response['final_answer'] = str(upload_context.get('extraction_error') or '语音识别失败')
            memory_store.append_turn(conversation_id, question, response['final_answer'])
            memory_store.update_profile(conversation_id, {'last_question': question, 'last_upload': upload_context, 'intent': 'general_chat'})
            return response
        transcript = str(upload_context.get('extracted_text') or '').strip()
        if upload_context.get('file_kind') == 'audio' and transcript:
            merged_question = transcript
        else:
            merged_question = _merge_question_with_file_context(question, upload_context)
        request_payload = ChatRequest(
            question=merged_question,
            conversation_id=conversation_id,
            image_context=None,
            origin=origin,
            destination=destination,
            preferences=preferences,
            travel_mode=travel_mode,
            waypoint_order=str(waypoint_order).lower() == 'true' if waypoint_order is not None else None,
            waypoints_json=waypoints_json,
            force_current_anchor=True,
        )
    intent = _classify_chat_intent(merged_question)
    try:
        if intent == 'general_chat':
            response = _build_general_response(request_payload)
            response['final_answer'] = await _generate_general_answer(merged_question, conversation_id)
        else:
            graph_result = await asyncio.wait_for(unified_graph.ainvoke({
                'request': request_payload,
                'upload_context': upload_context,
            }), timeout=45)
            response = graph_result.get('response') or _build_general_response(request_payload)
            if response.get('answer_type') == 'travel_planning' and response.get('travel_request') is None:
                response['travel_request'] = _build_travel_request(request_payload).model_dump()
            if _looks_like_general_chat(merged_question) and response.get('answer_type') == 'travel_planning':
                response = _build_general_response(request_payload)
                response['final_answer'] = await _generate_general_answer(merged_question, conversation_id)
            elif response.get('answer_type') == 'general_chat' and not str(response.get('final_answer') or '').strip():
                response['final_answer'] = await _generate_general_answer(merged_question, conversation_id)
    except asyncio.TimeoutError:
        response = _build_general_response(request_payload)
        response['final_answer'] = '请求处理超时：后端 Agent 在限定时间内没有返回结果，请检查地图/模型接口配置或稍后重试。'
        response['error'] = 'graph_timeout'
    except Exception as exc:
        response = _build_general_response(request_payload)
        response['final_answer'] = f'请求处理失败：{exc}'
        response['error'] = str(exc)
    if upload_context and response.get('upload_context') is None:
        response['upload_context'] = upload_context
        transcript = str(upload_context.get('extracted_text') or '').strip()
        if upload_context.get('file_kind') == 'audio' and transcript:
            response['final_answer'] = response.get('final_answer') or transcript
        elif upload_context.get('file_kind') == 'image':
            response['final_answer'] = response.get('final_answer') or f'已接收图片 {upload_context["filename"]}'
        elif upload_context.get('file_kind') in {'text', 'pdf'}:
            if not str(response.get('final_answer') or '').strip() and transcript:
                response['final_answer'] = await _generate_general_answer(transcript, conversation_id)
        else:
            response['final_answer'] = response.get('final_answer') or f'已接收{upload_context["file_kind"]} {upload_context["filename"]}'
    memory_store.append_turn(conversation_id, question, response['final_answer'])
    memory_store.update_profile(conversation_id, {'last_question': question, 'last_upload': upload_context, 'intent': intent})
    return response
