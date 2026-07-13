import pytest

from travel_agent.core.config import Settings
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.services import llm_chat_service


def test_settings_can_instantiate_without_service_keys():
    settings = Settings(_env_file=None)
    assert settings.qwen_api_key == ''
    assert settings.tencent_maps_key == ''
    assert settings.redis_url.startswith('redis://')
    assert settings.memory_ttl_seconds > 0


@pytest.mark.asyncio
async def test_general_answer_degrades_when_llm_key_missing(monkeypatch):
    monkeypatch.setattr(llm_chat_service.settings, 'qwen_api_key', '')
    answer = await llm_chat_service.generate_general_answer('你好', 'missing-key')
    assert answer == '模型服务未配置，无法完成普通问答。'


def test_redis_memory_falls_back_quickly_when_redis_unavailable(monkeypatch):
    import travel_agent.memory.redis_memory as redis_memory

    class FailingRedis:
        def ping(self):
            raise TimeoutError('redis unavailable')

    def fake_from_url(*args, **kwargs):
        assert kwargs['socket_connect_timeout'] <= 0.5
        assert kwargs['socket_timeout'] <= 0.5
        return FailingRedis()

    monkeypatch.setattr(redis_memory.redis, 'from_url', fake_from_url)
    store = RedisMemoryStore()
    assert store.get_context('x') == {'short_term': [], 'long_term': {}}
