from __future__ import annotations

from typing import Any
from urllib.parse import quote
import re

import httpx

from travel_agent.core.config import get_settings

settings = get_settings()


class TencentWebServiceError(RuntimeError):
    pass


_CITY_SUFFIXES = ('市', '省', '自治区', '特别行政区', '区', '县')


class TencentWebServiceClient:
    def __init__(self) -> None:
        self.base_url = settings.tencent_maps_base_url.rstrip('/')
        self.key = settings.tencent_maps_key

    def _request(self, path: str, params: dict[str, Any], *, output: str = 'json') -> dict[str, Any]:
        if not self.key:
            raise TencentWebServiceError('Tencent Maps key is not configured')
        query = {**params, 'key': self.key, 'output': output}
        url = f'{self.base_url}{path}'
        with httpx.Client(timeout=12.0) as client:
            response = client.get(url, params=query)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise TencentWebServiceError('Tencent WebService returned invalid payload')
        if data.get('status') not in (0, '0'):
            raise TencentWebServiceError(str(data.get('message') or data.get('info') or 'Tencent WebService error'))
        return data

    def _infer_region(self, text: str | None) -> str | None:
        if not text:
            return None
        cleaned = re.sub(r'[\s，。；,！？]+', '', text)
        for suffix in _CITY_SUFFIXES:
            if cleaned.endswith(suffix):
                return cleaned
        match = re.search(r'(.+?(?:市|自治区|特别行政区|区|县))', cleaned)
        if match:
            return match.group(1)
        if '北京' in cleaned:
            return '北京'
        if '上海' in cleaned:
            return '上海'
        if '天津' in cleaned:
            return '天津'
        if '重庆' in cleaned:
            return '重庆'
        return None

    def _clean_address(self, address: str) -> str:
        text = address.strip()
        text = re.sub(r'^(从|自|由)', '', text)
        text = re.sub(r'(出发地|出发|目的地|前往|到|去)$', '', text)
        text = re.sub(r'[，。；,！？]+$', '', text)
        return text.strip()

    def geocoder(self, address: str, region: str | None = None) -> dict[str, Any]:
        clean_address = self._clean_address(address)
        params: dict[str, Any] = {'address': clean_address}
        params['region'] = region or self._infer_region(clean_address) or '北京'
        return self._request('/ws/geocoder/v1', params)

    def reverse_geocoder(self, location: str) -> dict[str, Any]:
        return self._request('/ws/geocoder/v1', {'location': location})

    def smart_geocoder(self, address: str, region: str | None = None) -> dict[str, Any]:
        clean_address = self._clean_address(address)
        params: dict[str, Any] = {'address': clean_address}
        params['region'] = region or self._infer_region(clean_address) or '北京'
        return self._request('/ws/geocoder/v1', params)

    def geocoder_hd(self, address: str, region: str | None = None) -> dict[str, Any]:
        clean_address = self._clean_address(address)
        params: dict[str, Any] = {'address': clean_address}
        params['region'] = region or self._infer_region(clean_address) or '北京'
        return self._request('/ws/geocoder/v1', params)

    def district_list(self, region: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if region:
            params['region'] = region
        return self._request('/ws/district/v1/list', params)

    def district_children(self, id_: str) -> dict[str, Any]:
        return self._request('/ws/district/v1/getchildren', {'id': id_})

    def district_search(self, keyword: str, region: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {'keyword': keyword}
        if region:
            params['region'] = region
        return self._request('/ws/district/v1/search', params)

    def suggestion(self, keyword: str, region: str | None = None, policy: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {'keyword': keyword}
        if region:
            params['region'] = region
        if policy is not None:
            params['policy'] = policy
        return self._request('/ws/place/v1/suggestion', params)

    def place_search(self, keyword: str, boundary: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {'keyword': keyword}
        if boundary:
            params['boundary'] = boundary
        return self._request('/ws/place/v1/search', params)

    def place_detail(self, id_: str) -> dict[str, Any]:
        return self._request('/ws/place/v1/detail', {'id': id_})

    def place_nearby(self, keyword: str, location: str, radius: int = 1000) -> dict[str, Any]:
        boundary = f'nearby({location},{radius})'
        return self.place_search(keyword, boundary=boundary)

    def place_search_by_region(self, keyword: str, region: str, page_size: int = 10, page_index: int = 1, filter_value: str | None = None, orderby: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            'keyword': keyword,
            'boundary': f'region({quote(region)},{1})',
            'page_size': page_size,
            'page_index': page_index,
        }
        if filter_value:
            params['filter'] = filter_value
        if orderby:
            params['orderby'] = orderby
        return self._request('/ws/place/v1/search', params)

    def place_search_nearby_sorted(self, keyword: str, location: str, radius: int = 1500, page_size: int = 10, page_index: int = 1, filter_value: str | None = None, orderby: str = '_distance') -> dict[str, Any]:
        params: dict[str, Any] = {
            'keyword': keyword,
            'boundary': f'nearby({location},{radius})',
            'page_size': page_size,
            'page_index': page_index,
            'orderby': orderby,
        }
        if filter_value:
            params['filter'] = filter_value
        return self._request('/ws/place/v1/search', params)

    def alongby(self, keyword: str, start: str, end: str, radius: int = 1000) -> dict[str, Any]:
        boundary = f'alongby({start},{end},{radius})'
        return self.place_search(keyword, boundary=boundary)

    def aoi_search(self, keyword: str, boundary: str) -> dict[str, Any]:
        return self.place_search(keyword, boundary=boundary)

    def dangerous_place(self, keyword: str, location: str) -> dict[str, Any]:
        return self.place_search(keyword, boundary=f'nearby({location},1000)')

    def poi_association(self, keyword: str, location: str) -> dict[str, Any]:
        return self.place_search(keyword, boundary=f'nearby({location},2000)')

    def route(self, mode: str, origin: str, destination: str, *, waypoints: list[str] | None = None, waypoint_order: bool = False, policy: str | None = None, departure_time: str | None = None) -> dict[str, Any]:
        path_map = {
            'driving': '/ws/direction/v1/driving',
            'walking': '/ws/direction/v1/walking',
            'transit': '/ws/direction/v1/transit',
            'bicycling': '/ws/direction/v1/bicycling',
            'trucking': '/ws/direction/v1/truck',
        }
        path = path_map.get(mode)
        if not path:
            raise TencentWebServiceError(f'Unsupported route mode: {mode}')
        params: dict[str, Any] = {'from': origin, 'to': destination}
        if waypoints:
            params['waypoints'] = ';'.join(waypoints)
        if waypoint_order:
            params['waypoint_order'] = 1
        if policy:
            params['policy'] = policy
        if departure_time:
            params['departure_time'] = departure_time
        if mode == 'driving':
            params['get_mp'] = 1
            params['get_speed'] = 1
        return self._request(path, params)

    def matrix(self, mode: str, origins: list[str], destinations: list[str]) -> dict[str, Any]:
        return self._request('/ws/distance/v1/matrix', {'mode': mode, 'from': ';'.join(origins), 'to': ';'.join(destinations)})

    def future_eta(self, mode: str, origin: str, destination: str, departure_time: str) -> dict[str, Any]:
        return self.route(mode, origin, destination, departure_time=departure_time, policy='LEAST_TIME')

    def travel_range(self, origin: str, threshold: int = 3000, mode: str = 'driving') -> dict[str, Any]:
        return self._request('/ws/distance/v1/matrix', {'mode': mode, 'from': origin, 'to': origin, 'max_distance': threshold})

    def scheduler(self, origin: str, destinations: list[str], mode: str = 'driving') -> dict[str, Any]:
        return self._request('/ws/distance/v1/matrix', {'mode': mode, 'from': origin, 'to': ';'.join(destinations)})

    def webservice_translate(self, text: str, to: str = 'zh') -> dict[str, Any]:
        return {'text': text, 'to': to, 'translated': text}

    def ip_location(self, ip: str) -> dict[str, Any]:
        return self._request('/ws/location/v1/ip', {'ip': ip})

    def location(self, lat: float, lng: float) -> dict[str, Any]:
        return self.reverse_geocoder(f'{lat},{lng}')

    def weather_info(self, adcode: str, weather_type: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {'adcode': adcode}
        if weather_type:
            params['type'] = weather_type
        return self._request('/ws/weather/v1', params)

    def wmts(self, layer: str, tile_matrix: str, tile_row: str, tile_col: str) -> dict[str, Any]:
        return {'layer': layer, 'tile_matrix': tile_matrix, 'tile_row': tile_row, 'tile_col': tile_col}
