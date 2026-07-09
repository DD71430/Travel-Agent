from travel_agent.schemas.chat import ChatRequest
from travel_agent.services import nearby_service


def test_search_nearby_without_key(monkeypatch):
    monkeypatch.setattr(nearby_service.settings, 'tencent_maps_key', '')
    candidates, debug = nearby_service.search_nearby_category('酒店', '故宫', None, '北京')
    assert candidates == []
    assert debug['reason'] == 'missing_key'


def test_build_nearby_without_key(monkeypatch):
    monkeypatch.setattr(nearby_service.settings, 'tencent_maps_key', '')
    response = nearby_service.build_nearby_response(ChatRequest(question='故宫附近酒店餐厅景点', conversation_id='c1'))
    assert response['answer_type'] == 'nearby_search'
    assert response['data']['nearby']['hotel_candidates'] == []
    assert response['error'] is None
