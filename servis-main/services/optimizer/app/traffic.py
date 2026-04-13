import asyncio
import aiohttp
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import json
import numpy as np
import hashlib


class MultiSourceTrafficIntegrator:
    """
    Tüm koordinatlar (lon, lat). Dış API'lere giderken (lat,lon) çevrilir.
    """
    def __init__(self, google_api_key: str, here_api_key: str, redis_client):
        self.google_key = google_api_key
        self.here_key = here_api_key
        self.redis = redis_client
        self.fallback_factors = self._load_historical_patterns()

    async def get_traffic_matrix(self, coordinates: List[Tuple[float, float]], departure_time: Optional[datetime] = None) -> np.ndarray:
        if departure_time is None:
            departure_time = datetime.utcnow()

        tasks = [
            self._get_google_matrix(coordinates, departure_time),
            self._get_here_matrix(coordinates, departure_time),
            self._get_historical_matrix(coordinates, departure_time)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        google_data, here_data, historical_data = results

        if isinstance(google_data, Exception) or google_data is None:
            google_data = None
        if isinstance(here_data, Exception) or here_data is None:
            here_data = None
        if isinstance(historical_data, Exception) or historical_data is None:
            raise RuntimeError("Historical matrix missing — base OSRM required for fallback")

        return self._combine(google_data, here_data, historical_data)

    async def _get_google_matrix(self, coords: List[Tuple[float, float]], dt: datetime) -> Optional[np.ndarray]:
        try:
            url = "https://maps.googleapis.com/maps/api/distancematrix/json"
            points_ll = [f"{lat},{lon}" for (lon, lat) in coords]
            origins = "|".join(points_ll)
            params = {
                'origins': origins,
                'destinations': origins,
                'mode': 'driving',
                'departure_time': int(dt.timestamp()),
                'traffic_model': 'best_guess',
                'key': self.google_key
            }
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params=params, timeout=10) as resp:
                    data = await resp.json()
            if data.get('status') != 'OK':
                return None
            matrix = []
            for row in data.get('rows', []):
                row_vals = []
                for el in row.get('elements', []):
                    if el.get('status') == 'OK':
                        dur = el.get('duration_in_traffic', el.get('duration', {'value': None}))['value']
                        row_vals.append(int(dur) if dur is not None else 0)
                    else:
                        row_vals.append(0)
                matrix.append(row_vals)
            return np.array(matrix, dtype=int)
        except Exception:
            return None

    async def _get_here_matrix(self, coords: List[Tuple[float, float]], dt: datetime) -> Optional[np.ndarray]:
        try:
            url = "https://matrix.route.ls.hereapi.com/routing/7.2/calculatematrix.json"
            starts = [{"lat": lat, "lng": lon} for (lon, lat) in coords]
            payload = {
                'start': starts,
                'destination': starts,
                'mode': 'fastest;car;traffic:enabled',
                'departureTime': dt.isoformat(),
                'apiKey': self.here_key
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=10) as resp:
                    data = await resp.json()
            resp_obj = data.get('response')
            if not resp_obj:
                return None
            size = len(coords)
            mat = np.zeros((size, size), dtype=int)
            for entry in resp_obj.get('matrixEntry', []):
                i, j = entry['startIndex'], entry['destinationIndex']
                t = entry.get('summary', {}).get('travelTime')
                if t is not None:
                    mat[i, j] = int(t)
            return mat
        except Exception:
            return None

    async def _get_historical_matrix(self, coords: List[Tuple[float, float]], dt: datetime) -> np.ndarray:
        hour, wd = dt.hour, dt.weekday()
        key = f"traffic:pattern:{hour}:{wd}"
        cached = await self.redis.get(key)
        factor = float(json.loads(cached)) if cached else float(self.fallback_factors.get(f"{hour}:{wd}", 1.0))
        base = await self._get_osrm_matrix(coords)
        return (base * factor).astype(int)

    async def _get_osrm_matrix(self, coords: List[Tuple[float, float]]) -> np.ndarray:
        raise NotImplementedError("OSRM client entegrasyonu gerekli")

    def _combine(self, g: Optional[np.ndarray], h: Optional[np.ndarray], hist: np.ndarray) -> np.ndarray:
        weights = []
        mats = []
        if g is not None:
            mats.append(g)
            weights.append(0.5)
        if h is not None:
            mats.append(h)
            weights.append(0.3)
        mats.append(hist)
        weights.append(0.2)

        weights = np.array(weights, dtype=float)
        weights = weights / weights.sum()
        stacked = np.stack(mats, axis=0)
        out = np.average(stacked, axis=0, weights=weights)
        return out.astype(int)

    def _load_historical_patterns(self) -> Dict[str, float]:
        return {
            **{f"7:{d}": 1.4 for d in range(5)},
            **{f"8:{d}": 1.6 for d in range(5)},
            **{f"9:{d}": 1.3 for d in range(5)},
            **{f"17:{d}": 1.5 for d in range(5)},
            **{f"18:{d}": 1.7 for d in range(5)},
            **{f"19:{d}": 1.4 for d in range(5)},
            **{f"7:{d}": 1.1 for d in [5, 6]},
            **{f"8:{d}": 1.2 for d in [5, 6]},
            **{f"9:{d}": 1.1 for d in [5, 6]},
        }


class SmartMatrixCache:
    """
    Basit ve güvenli cache: koordinat sırasını korur.
    Matris sıra duyarlı olduğu için coord listesi asla sort edilmez.
    """
    def __init__(self, redis_client, osrm_client, max_matrix_size=100):
        self.redis = redis_client
        self.osrm = osrm_client
        self.max_matrix_size = max_matrix_size

    async def get_matrix(self, coords: List[Tuple[float, float]]) -> np.ndarray:
        key = self._key(coords)
        if self.redis is not None:
            cached = await self.redis.get(key)
            if cached:
                return np.array(json.loads(cached), dtype=int)

        mat = await self.osrm.table(coords)
        if self.redis is not None:
            await self.redis.setex(key, 6 * 3600, json.dumps(mat))
        return np.array(mat, dtype=int)

    def _key(self, coords: List[Tuple[float, float]]) -> str:
        normalized = [[round(lon, 6), round(lat, 6)] for lon, lat in coords]
        coord_str = json.dumps(normalized, separators=(",", ":"))
        return f"matrix:{hashlib.sha256(coord_str.encode()).hexdigest()[:16]}"
