from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

import redis

from travel_agent.core.config import get_settings

settings = get_settings()

_MERGE_LIST_FIELDS = {'travel_preferences', 'interest_tags', 'avoid_tags', 'weather_sensitivity'}


class RedisMemoryStore:
    def __init__(self) -> None:
        self._prefix = settings.redis_prefix.strip() or 'travel_agent'
        self._short_term_limit = 10
        self._ttl = max(60, int(settings.memory_ttl_seconds))
        self._fallback_short_term: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._fallback_long_term: dict[str, dict[str, Any]] = defaultdict(dict)
        self._fallback_conversation_meta: dict[str, dict[str, Any]] = defaultdict(dict)
        self._fallback_conversation_scores: dict[str, float] = {}
        self._fallback_reason: str | None = None
        self._client = self._create_client()

    def _create_client(self):
        try:
            client = redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=0.2, socket_timeout=0.2)
            client.ping()
            return client
        except Exception as exc:
            self._fallback_reason = exc.__class__.__name__
            return None

    def _using_fallback(self) -> bool:
        return self._client is None

    def status(self) -> dict[str, Any]:
        status = {
            'backend': 'memory_fallback' if self._using_fallback() else 'redis',
            'connected': not self._using_fallback(),
            'prefix': self._prefix,
            'ttl_seconds': self._ttl,
            'short_term_limit': self._short_term_limit,
        }
        if self._using_fallback() and self._fallback_reason:
            status['fallback_reason'] = self._fallback_reason
        return status

    def _short_term_key(self, conversation_id: str) -> str:
        return f'{self._prefix}:memory:{conversation_id}:short_term'

    def _long_term_key(self, conversation_id: str) -> str:
        return f'{self._prefix}:memory:{conversation_id}:long_term'

    def _conversation_index_key(self) -> str:
        return f'{self._prefix}:conversations'

    def _conversation_meta_key(self, conversation_id: str) -> str:
        return f'{self._prefix}:conversation:{conversation_id}:meta'

    def _safe_json_load(self, raw: str | None, fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    def _merge_profile_patch(self, existing: dict[str, Any], profile_patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing)
        for field, value in profile_patch.items():
            if value is None:
                continue
            if field in _MERGE_LIST_FIELDS:
                old_items = merged.get(field, [])
                if not isinstance(old_items, list):
                    old_items = [old_items] if old_items else []
                new_items = value if isinstance(value, list) else [value]
                result: list[Any] = []
                for item in [*old_items, *new_items]:
                    if item in (None, ''):
                        continue
                    if item not in result:
                        result.append(item)
                merged[field] = result
            else:
                merged[field] = value
        return merged

    def _serialise_meta(self, meta: dict[str, Any]) -> dict[str, str]:
        serialised: dict[str, str] = {}
        for key, value in meta.items():
            if value is None:
                continue
            serialised[key] = str(value)
        return serialised

    def _clean_title(self, user_input: str) -> str:
        cleaned = ' '.join(str(user_input or '').split())
        return cleaned[:24] if len(cleaned) > 24 else cleaned

    def _meta_from_turn(self, conversation_id: str, user_input: str, assistant_output: str) -> dict[str, Any]:
        return {
            'conversation_id': conversation_id,
            'last_user_input': user_input,
            'last_assistant_output': assistant_output,
            'title': self._clean_title(user_input) or conversation_id[:8],
            'updated_at': str(time.time()),
        }

    def _read_conversation_meta(self, conversation_id: str) -> dict[str, Any]:
        if self._using_fallback():
            return dict(self._fallback_conversation_meta.get(conversation_id, {}))
        meta = self._client.hgetall(self._conversation_meta_key(conversation_id))
        return dict(meta or {})

    def _write_conversation_meta(self, conversation_id: str, meta: dict[str, Any]) -> None:
        updated_at = float(meta.get('updated_at') or time.time())
        if self._using_fallback():
            self._fallback_conversation_meta[conversation_id] = dict(meta)
            self._fallback_conversation_scores[conversation_id] = updated_at
            return
        serialised = self._serialise_meta(meta)
        pipe = self._client.pipeline(transaction=False)
        pipe.zadd(self._conversation_index_key(), {conversation_id: updated_at})
        if serialised:
            pipe.hset(self._conversation_meta_key(conversation_id), mapping=serialised)
        pipe.expire(self._conversation_meta_key(conversation_id), self._ttl)
        pipe.execute()

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
            existing_meta = self._read_conversation_meta(conversation_id)
            self._write_conversation_meta(conversation_id, {**existing_meta, **self._meta_from_turn(conversation_id, user_input, assistant_output)})
            return
        key = self._short_term_key(conversation_id)
        payload = json.dumps(payload_obj, ensure_ascii=False)
        pipe = self._client.pipeline(transaction=False)
        pipe.rpush(key, payload)
        pipe.ltrim(key, -self._short_term_limit, -1)
        pipe.expire(key, self._ttl)
        pipe.execute()
        existing_meta = self._read_conversation_meta(conversation_id)
        self._write_conversation_meta(conversation_id, {**existing_meta, **self._meta_from_turn(conversation_id, user_input, assistant_output)})

    def update_profile(self, conversation_id: str, profile_patch: dict[str, Any]) -> None:
        existing = self.get_context(conversation_id).get('long_term', {})
        merged = self._merge_profile_patch(existing if isinstance(existing, dict) else {}, profile_patch)
        if self._using_fallback():
            self._fallback_long_term[conversation_id] = merged
            return
        key = self._long_term_key(conversation_id)
        serialised = {field: json.dumps(value, ensure_ascii=False) for field, value in merged.items()}
        pipe = self._client.pipeline(transaction=False)
        if serialised:
            pipe.hset(key, mapping=serialised)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def update_conversation_meta(self, conversation_id: str, **fields: Any) -> None:
        existing = self._read_conversation_meta(conversation_id)
        merged = {**existing, **{key: value for key, value in fields.items() if value is not None}}
        merged.setdefault('conversation_id', conversation_id)
        merged.setdefault('title', self._clean_title(str(merged.get('last_user_input') or '')) or conversation_id[:8])
        merged['updated_at'] = str(time.time())
        self._write_conversation_meta(conversation_id, merged)

    def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 20), 100))
        if self._using_fallback():
            conversation_ids = [
                conversation_id
                for conversation_id, _score in sorted(self._fallback_conversation_scores.items(), key=lambda item: item[1], reverse=True)
            ][:safe_limit]
        else:
            conversation_ids = self._client.zrevrange(self._conversation_index_key(), 0, safe_limit - 1)
        conversations: list[dict[str, Any]] = []
        for conversation_id in conversation_ids:
            meta = self._read_conversation_meta(str(conversation_id))
            if not meta:
                continue
            meta.setdefault('conversation_id', str(conversation_id))
            meta.setdefault('title', self._clean_title(str(meta.get('last_user_input') or '')) or str(conversation_id)[:8])
            conversations.append(meta)
        return conversations

    def get_history(self, conversation_id: str, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or self._short_term_limit), self._short_term_limit))
        history = self.get_context(conversation_id).get('short_term', [])
        if not isinstance(history, list):
            return []
        return [item for item in history[-safe_limit:] if isinstance(item, dict)]

    def clear_conversation(self, conversation_id: str) -> None:
        if self._using_fallback():
            self._fallback_short_term.pop(conversation_id, None)
            self._fallback_long_term.pop(conversation_id, None)
            self._fallback_conversation_meta.pop(conversation_id, None)
            self._fallback_conversation_scores.pop(conversation_id, None)
            return
        self._client.delete(self._short_term_key(conversation_id), self._long_term_key(conversation_id), self._conversation_meta_key(conversation_id))
        self._client.zrem(self._conversation_index_key(), conversation_id)
