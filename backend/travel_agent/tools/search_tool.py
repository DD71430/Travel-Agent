from __future__ import annotations

from typing import Any

from travel_agent.tools.base import BaseTool
from travel_agent.tools.tencent_webservice_client import TencentWebServiceClient, TencentWebServiceError


class SearchTool(BaseTool):
    name = 'search'

    def __init__(self) -> None:
        self.client = TencentWebServiceClient()

    def _safe_call(self, func, *args, **kwargs) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except TencentWebServiceError as exc:
            return {'error': str(exc)}

    def run(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get('query', '')).strip()
        location = str(kwargs.get('location', '')).strip()
        region = kwargs.get('region')
        if not query:
            return {'query': query, 'results': [], 'source': 'empty_query'}

        suggestion = self._safe_call(self.client.suggestion, query, region=region)
        district = self._safe_call(self.client.district_search, query, region=region)
        place_search = self._safe_call(self.client.place_search, query, boundary=f'region({region})' if region else None)
        nearby = self._safe_call(self.client.place_nearby, query, location=location or '39.9087,116.3975', radius=2000)
        reverse = self._safe_call(self.client.reverse_geocoder, location or '39.9087,116.3975')
        translated = self.client.webservice_translate(query, to='zh')
        aoi = self._safe_call(self.client.aoi_search, query, boundary=f'region({region})' if region else 'region(全国)')
        dangerous = self._safe_call(self.client.dangerous_place, query, location=location or '39.9087,116.3975')
        poi_assoc = self._safe_call(self.client.poi_association, query, location=location or '39.9087,116.3975')

        results = []
        for label, payload in [
            ('地点输入提示', suggestion),
            ('行政区检索', district),
            ('地点搜索', place_search),
            ('周边搜索', nearby),
            ('AOI 检索', aoi),
            ('危险地点分析', dangerous),
            ('POI 关联', poi_assoc),
        ]:
            if 'error' in payload:
                continue
            items = payload.get('data') or payload.get('result') or payload.get('suggestions') or []
            if isinstance(items, dict):
                items = [items]
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                title = item.get('title') or item.get('name') or item.get('address') or query
                address = item.get('address') or item.get('ad_info', {}).get('name') or item.get('district') or ''
                results.append({
                    'title': str(title),
                    'snippet': f'{label}：{address}'.strip('：'),
                    'url': 'https://lbs.qq.com/',
                    'source': label,
                })
        if reverse and isinstance(reverse, dict):
            results.append({'title': '逆地理解析', 'snippet': str(reverse.get('result', reverse.get('message', ''))), 'url': 'https://lbs.qq.com/', 'source': '逆地址解析'})
        results.append({'title': '翻译/归一化', 'snippet': str(translated.get('translated', query)), 'url': 'https://lbs.qq.com/', 'source': 'webServiceTranslate'})
        return {
            'query': query,
            'location': location,
            'region': region,
            'results': results[:12],
            'raw': {
                'suggestion': suggestion,
                'district': district,
                'place_search': place_search,
                'nearby': nearby,
                'reverse': reverse,
                'translated': translated,
                'aoi': aoi,
                'dangerous': dangerous,
                'poi_association': poi_assoc,
            },
            'source': 'tencent_webservice',
        }
