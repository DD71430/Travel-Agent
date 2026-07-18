from __future__ import annotations

import re

_STOPOVER_ACTION_SUFFIX = re.compile(
    r'(?:并且?|且)?(?:停留|游玩|玩|住宿|住|看看|参观)'
    r'(?:\s*(?:半|\d+|[一二两三四五六七八九十]+))?\s*(?:半天|天|日|晚|一晚)?.*$'
)
_STOPOVER_DURATION_SUFFIX = re.compile(r'(?:半天|一晚|\d+\s*[天日晚]|[一二两三四五六七八九十]+\s*[天日晚]).*$')


def strip_stopover_action_suffix(value: str) -> str:
    cleaned = value.strip(' ，。；;、!?！?')
    cleaned = _STOPOVER_ACTION_SUFFIX.sub('', cleaned)
    cleaned = _STOPOVER_DURATION_SUFFIX.sub('', cleaned)
    cleaned = re.sub(r'(?:并且?|且)$', '', cleaned)
    return cleaned.strip(' ，。；;、!?！?')
