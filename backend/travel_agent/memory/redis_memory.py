from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import redis

from travel_agent.core.config import get_settings

settings = get_settings()


class RedisMemoryStore:
    def __init__(self) -> None:
        self._prefix = settings.redis_prefix.strip() or 'travel_agent'
        self._short_term_limit = 10
        self._ttl = max(60, int(settings.memory_ttl_seconds))
        self._fallback_short_term: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._fallback_long_term: dict[str, dict[str, Any]] = defaultdict(dict)
        self._client = self._create_client()

    def _create_client(self):
        try:
            client = redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            return None

    def _using_fallback(self) -> bool:
        return self._client is None

    def _short_term_key(self, conversation_id: str) -> str:
        return f'{self._prefix}:memory:{conversation_id}:short_term'

    def _long_term_key(self, conversation_id: str) -> str:
        return f'{self._prefix}:memory:{conversation_id}:long_term'

    def _safe_json_load(self, raw: str | None, fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    def get_context(self, conversation_id: str) -> dict[str, Any]:
        if self._using_fallback():
            return {
                'short_term': self._fallback_short_term[conversation_id][-self._short_term_limit:],
                'long_term': self._fallback_long_term[conversation_id],
            }
        short_term_raw = self._client.lrange(self._short_term_key(conversation_id), -self._short_term_limit, -1)
        short_term = [self._safe_json_load(item, {}) for item in short_term_raw]
        long_term_raw = self._client.hgetall(self._long_term_key(conversation_id))
        long_term = {key: self._safe_json_load(value, value) for key, value in long_term_raw.items()}
        return {
            'short_term': short_term,
            'long_term': long_term,
        }

    def append_turn(self, conversation_id: str, user_input: str, assistant_output: str) -> None:
        payload_obj = {'user_input': user_input, 'assistant_output': assistant_output}
        if self._using_fallback():
            self._fallback_short_term[conversation_id].append(payload_obj)
            self._fallback_short_term[conversation_id] = self._fallback_short_term[conversation_id][-self._short_term_limit:]
            return
        key = self._short_term_key(conversation_id)
        payload = json.dumps(payload_obj, ensure_ascii=False)
        pipe = self._client.pipeline(transaction=False)
        pipe.rpush(key, payload)
        pipe.ltrim(key, -self._short_term_limit, -1)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def update_profile(self, conversation_id: str, profile_patch: dict[str, Any]) -> None:
        if self._using_fallback():
            self._fallback_long_term[conversation_id].update(profile_patch)
            return
        key = self._long_term_key(conversation_id)
        serialised = {field: json.dumps(value, ensure_ascii=False) for field, value in profile_patch.items()}
        pipe = self._client.pipeline(transaction=False)
        if serialised:
            pipe.hset(key, mapping=serialised)
        pipe.expire(key, self._ttl)
        pipe.execute()
