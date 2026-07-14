import pytest

from travel_agent.api import chat as chat_api
from travel_agent.core.config import Settings
from travel_agent.memory.redis_memory import RedisMemoryStore
from travel_agent.schemas.chat import ChatRequest
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
    status = store.status()
    assert status['backend'] == 'memory_fallback'
    assert status['connected'] is False
    assert status['fallback_reason']


def test_redis_memory_fake_client_sets_ttl_and_merges_profile(monkeypatch):
    import travel_agent.memory.redis_memory as redis_memory

    class FakePipeline:
        def __init__(self, client):
            self.client = client
            self.commands = []

        def rpush(self, key, payload):
            self.commands.append(('rpush', key, payload))
            return self

        def ltrim(self, key, start, end):
            self.commands.append(('ltrim', key, start, end))
            return self

        def expire(self, key, ttl):
            self.commands.append(('expire', key, ttl))
            return self

        def hset(self, key, mapping):
            self.commands.append(('hset', key, mapping))
            return self

        def zadd(self, key, mapping):
            self.commands.append(('zadd', key, mapping))
            return self

        def execute(self):
            for command in self.commands:
                if command[0] == 'rpush':
                    _, key, payload = command
                    self.client.lists.setdefault(key, []).append(payload)
                elif command[0] == 'ltrim':
                    _, key, start, end = command
                    values = self.client.lists.get(key, [])
                    self.client.lists[key] = values[start:] if end == -1 else values[start : end + 1]
                elif command[0] == 'expire':
                    _, key, ttl = command
                    self.client.expirations[key] = ttl
                elif command[0] == 'hset':
                    _, key, mapping = command
                    self.client.hashes.setdefault(key, {}).update(mapping)
                elif command[0] == 'zadd':
                    _, key, mapping = command
                    self.client.zsets.setdefault(key, {}).update(mapping)
            return []

    class FakeRedis:
        def __init__(self):
            self.lists = {}
            self.hashes = {}
            self.zsets = {}
            self.expirations = {}

        def ping(self):
            return True

        def lrange(self, key, start, end):
            values = self.lists.get(key, [])
            return values[start:] if end == -1 else values[start : end + 1]

        def hgetall(self, key):
            return self.hashes.get(key, {})

        def pipeline(self, transaction=False):
            assert transaction is False
            return FakePipeline(self)

        def zrevrange(self, key, start, end):
            values = sorted(self.zsets.get(key, {}).items(), key=lambda item: item[1], reverse=True)
            return [item[0] for item in values[start : end + 1]]

    fake = FakeRedis()
    monkeypatch.setattr(redis_memory.redis, 'from_url', lambda *args, **kwargs: fake)
    store = RedisMemoryStore()

    store.append_turn('conv-a', '你好', '你好，已记录')
    store.append_turn('conv-b', '去杭州', '杭州行程')
    store.update_profile('conv-a', {'travel_preferences': ['博物馆'], 'interest_tags': ['历史文化'], 'last_origin': '济南'})
    store.update_profile('conv-a', {'travel_preferences': ['公园', '博物馆'], 'interest_tags': ['历史文化', '美食'], 'weather_sensitivity': ['怕热']})

    context_a = store.get_context('conv-a')
    context_b = store.get_context('conv-b')
    status = store.status()

    assert status['backend'] == 'redis'
    assert status['connected'] is True
    assert context_a['short_term'][0]['user_input'] == '你好'
    assert context_b['short_term'][0]['user_input'] == '去杭州'
    assert context_a['long_term']['travel_preferences'] == ['博物馆', '公园']
    assert context_a['long_term']['interest_tags'] == ['历史文化', '美食']
    assert context_a['long_term']['last_origin'] == '济南'
    assert context_a['long_term']['weather_sensitivity'] == ['怕热']
    assert all(ttl == status['ttl_seconds'] for ttl in fake.expirations.values())


def test_append_turn_indexes_conversation_in_fallback(monkeypatch):
    import travel_agent.memory.redis_memory as redis_memory

    monkeypatch.setattr(redis_memory.redis, 'from_url', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('redis unavailable')))
    store = RedisMemoryStore()

    store.append_turn('conv-a', '你好', '你好，已记录')
    store.append_turn('conv-b', '从杭州到西安三天两晚', '杭州到西安规划')
    store.update_conversation_meta('conv-b', intent='travel_planning')

    conversations = store.list_conversations(limit=10)

    assert [item['conversation_id'] for item in conversations] == ['conv-b', 'conv-a']
    assert conversations[0]['title'] == '从杭州到西安三天两晚'
    assert conversations[0]['intent'] == 'travel_planning'
    assert conversations[0]['last_assistant_output'] == '杭州到西安规划'


def test_get_history_returns_short_term_in_fallback(monkeypatch):
    import travel_agent.memory.redis_memory as redis_memory

    monkeypatch.setattr(redis_memory.redis, 'from_url', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('redis unavailable')))
    store = RedisMemoryStore()

    for index in range(12):
        store.append_turn('conv-a', f'问题{index}', f'回答{index}')

    history = store.get_history('conv-a', limit=3)

    assert [item['user_input'] for item in history] == ['问题9', '问题10', '问题11']
    assert [item['assistant_output'] for item in history] == ['回答9', '回答10', '回答11']


@pytest.mark.asyncio
async def test_chat_generates_uuid_when_conversation_id_missing_and_returns_memory_status(monkeypatch):
    class FakeMemoryStore:
        def __init__(self):
            self.context_ids = []
            self.appended = []

        def status(self):
            return {'backend': 'memory_fallback', 'connected': False, 'prefix': 'test', 'ttl_seconds': 60, 'short_term_limit': 10}

        def get_context(self, conversation_id):
            self.context_ids.append(conversation_id)
            return {'short_term': [], 'long_term': {}}

        def append_turn(self, conversation_id, user_question, final_answer):
            self.appended.append((conversation_id, user_question, final_answer))

        def update_profile(self, conversation_id, profile_patch):
            return None

    fake_store = FakeMemoryStore()

    async def fake_run_graph(request, upload_context=None):
        return {
            'conversation_id': request.conversation_id,
            'answer_type': 'general_chat',
            'final_answer': 'ok',
            'data': {},
            'travel_request': None,
            'upload_context': upload_context,
            'meta': {},
            'error': None,
        }

    monkeypatch.setattr(chat_api, 'memory_store', fake_store)
    monkeypatch.setattr(chat_api, '_run_graph', fake_run_graph)

    response = await chat_api.chat(ChatRequest(question='你好'))

    assert response['conversation_id'] != 'default'
    assert len(response['conversation_id']) == 36
    assert fake_store.context_ids == [response['conversation_id']]
    assert fake_store.appended[0][0] == response['conversation_id']
    assert response['meta']['memory']['backend'] == 'memory_fallback'
