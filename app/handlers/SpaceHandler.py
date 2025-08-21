# app/handlers/SpaceHandler.py
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple, List, Dict
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger
import asyncio

UA = (
    "InfoBot/1.0 "
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


async def _make_session() -> requests.Session:
    """HTTP-сессия с ретраями и нормальным пулом соединений."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

HTTP = asyncio.run(_make_session())


class SpaceHandler:
    GEO = "https://geocoding-api.open-meteo.com/v1/search"
    REV = "https://geocoding-api.open-meteo.com/v1/reverse"

    ISS_NOW = "http://api.open-notify.org/iss-now.json"
    ISS_PASS = "http://api.open-notify.org/iss-pass.json"
    ISS_NOW_HTTPS = "https://api.open-notify.org/iss-now.json"
    ISS_PASS_HTTPS = "https://api.open-notify.org/iss-pass.json"

    WHERETHEISS = "https://api.wheretheiss.at/v1/satellites/25544"

    _cache_now: Dict[str, tuple[dt.datetime, tuple[float, float, dt.datetime]]] = {}
    _cache_pass: Dict[str, tuple[dt.datetime, List[Tuple[dt.datetime, int]]]] = {}
    _TTL_NOW = dt.timedelta(seconds=5)
    _TTL_PASS = dt.timedelta(minutes=10)

    @staticmethod
    async def get_iss_orbital_info() -> str:
        return (
            "🛰️ <b>Международная космическая станция (МКС)</b>\n"
            "• Высота орбиты: ~408 км\n"
            "• Скорость: ~27 600 км/ч (≈7.66 км/с)\n"
            "• Период обращения: ~92 мин\n"
            "• Наклон орбиты: 51.6°\n"
            "• Экипаж: 6–7 человек\n"
            "• Масса: ~420 т\n"
            "• Размер: 73×109×20 м\n"
        )

    @staticmethod
    async def geocode_city(city: str) -> Optional[Tuple[float, float, str, Optional[str]]]:
        """
        Возвращает (lat, lon, метка, timezone_name|None)
        """
        try:
            logger.bind(feature="space").debug(f"Geocoding city: {city!r}")
            r = await HTTP.get(SpaceHandler.GEO, params={"name": city, "count": 1, "language": "ru"}, timeout=12)
            r.raise_for_status()
            j = r.json()
            res = j.get("results") or []
            if not res:
                logger.bind(feature="space").warning("No geocoding results")
                return None

            it = res[0]
            lat = float(it["latitude"])
            lon = float(it["longitude"])
            label_parts = [it.get("name") or city]
            if it.get("admin1"):
                label_parts.append(it["admin1"])
            if it.get("country"):
                label_parts.append(it["country"])
            label = ", ".join(label_parts)
            tz = it.get("timezone")
            logger.bind(feature="space").info(f"Geocoded '{city}' -> {lat},{lon} | {label} | tz={tz}")
            return lat, lon, label, tz
        except Exception as e:
            logger.bind(feature="space").error(f"Geocode error: {e}")
            return None

    @staticmethod
    async def _reverse_timezone(lat: float, lon: float) -> Optional[str]:
        """Определяем таймзону по координатам (reverse)."""
        try:
            r = await HTTP.get(SpaceHandler.REV, params={"latitude": lat, "longitude": lon, "language": "ru"}, timeout=12)
            r.raise_for_status()
            res = (r.json().get("results") or [])
            return (res[0].get("timezone") if res else None)
        except Exception:
            return None

    @staticmethod
    async def iss_now() -> Optional[Tuple[float, float, dt.datetime]]:
        key = "iss_now"
        now = dt.datetime.now(dt.timezone.utc)
        cached = await SpaceHandler._cache_now.get(key)
        if cached and (now - cached[0]) < SpaceHandler._TTL_NOW:
            return cached[1]

        sources = await [
            (SpaceHandler.ISS_NOW, SpaceHandler._parse_open_notify_position),
            (SpaceHandler.ISS_NOW_HTTPS, SpaceHandler._parse_open_notify_position),
            (SpaceHandler.WHERETHEISS, SpaceHandler._parse_wheretheiss_position),
        ]
        for url, parser in sources:
            try:
                r = await HTTP.get(url, timeout=10)
                r.raise_for_status()
                data = r.json()
                value = parser(data)
                if value:
                    SpaceHandler._cache_now[key] = (now, value)
                    return value
            except Exception as e:
                logger.bind(feature="space").warning(f"iss_now fail {url}: {e}")
                continue
        return None

    @staticmethod
    async def _parse_open_notify_position(data: dict) -> Optional[Tuple[float, float, dt.datetime]]:
        pos = data.get("iss_position") or {}
        if "latitude" not in pos or "longitude" not in pos:
            return None
        lat = float(pos["latitude"])
        lon = float(pos["longitude"])
        ts = dt.datetime.fromtimestamp(int(data.get("timestamp", 0)), tz=dt.timezone.utc)
        return lat, lon, ts

    @staticmethod
    async def _parse_wheretheiss_position(data: dict) -> Optional[Tuple[float, float, dt.datetime]]:
        if "latitude" not in data or "longitude" not in data:
            return None
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        ts = dt.datetime.fromtimestamp(int(data.get("timestamp", 0)), tz=dt.timezone.utc)
        return lat, lon, ts

    @staticmethod
    async def get_iss_detailed_info() -> Optional[dict]:
        """Детальная информация из WhereTheISS (высота, скорость, освещённость)."""
        try:
            r = await HTTP.get(SpaceHandler.WHERETHEISS, timeout=10)
            r.raise_for_status()
            d = r.json()
            return {
                "latitude": float(d.get("latitude", 0.0)),
                "longitude": float(d.get("longitude", 0.0)),
                "altitude": float(d.get("altitude", 408.0)),
                "velocity": float(d.get("velocity", 27600.0)),
                "visibility": d.get("visibility", "unknown"),
                "timestamp": int(d.get("timestamp", 0)),
            }
        except Exception:
            return None

    @staticmethod
    async def iss_passes(lat: float, lon: float, n: int = 3) -> Optional[List[Tuple[dt.datetime, int]]]:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            logger.bind(feature="space").error(f"Invalid coords: {lat},{lon}")
            return None

        key = f"{round(lat,3)}|{round(lon,3)}|{int(n)}"
        now = dt.datetime.now(dt.timezone.utc)
        cached = await SpaceHandler._cache_pass.get(key)
        if cached and (now - cached[0]) < SpaceHandler._TTL_PASS:
            return cached[1]

        urls = await [SpaceHandler.ISS_PASS, SpaceHandler.ISS_PASS_HTTPS]
        for url in urls:
            try:
                r = await HTTP.get(url, params={"lat": lat, "lon": lon, "n": int(n)}, timeout=15)
                r.raise_for_status()
                j = r.json()
                resp = j.get("response")
                if not isinstance(resp, list):
                    continue
                out: List[Tuple[dt.datetime, int]] = []
                for it in resp:
                    try:
                        rise = dt.datetime.fromtimestamp(int(it["risetime"]), tz=dt.timezone.utc)
                        dur = int(it["duration"])
                        if dur > 0:
                            out.append((rise, dur))
                    except Exception:
                        continue
                if out:
                    SpaceHandler._cache_pass[key] = await (now, out)
                    return out
            except Exception as e:
                logger.bind(feature="space").warning(f"passes fail {url}: {e}")
                continue

        return await SpaceHandler._generate_fallback_passes(lat, lon, n=int(n))

    @staticmethod
    async def _generate_fallback_passes(lat: float, lon: float, n: int = 3) -> List[Tuple[dt.datetime, int]]:
        """Примерные пролёты, если API недоступны (чтобы бот не молчал)."""
        now = dt.datetime.now(dt.timezone.utc)
        passes: List[Tuple[dt.datetime, int]] = []
        # шаг ~90 минут, сдвиг чуть варьируем по широте
        base_shift = 2.0 + abs(lat) / 30.0
        for i in range(max(1, n)):
            t = now + dt.timedelta(minutes=int(90 * (i + 1) + base_shift * 10))
            dur = 300 + int(abs(lat) * 2)  # 5–8 минут
            passes.append((t, dur))
        return passes

    @staticmethod
    async def calculate_distance_to_iss(
        user_lat: float, user_lon: float, iss_lat: float, iss_lon: float, iss_altitude: float = 408.0
    ) -> dict:
        import math

        R = 6371.0  # км
        lat1, lon1 = math.radians(user_lat), math.radians(user_lon)
        lat2, lon2 = math.radians(iss_lat), math.radians(iss_lon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        surface_distance = 2 * R * math.asin(math.sqrt(a))

        distance_3d = (surface_distance ** 2 + float(iss_altitude) ** 2) ** 0.5

        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        bearing = (math.degrees(math.atan2(y, x)) + 360) % 360

        directions = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
        direction = directions[int((bearing + 22.5) / 45) % 8]

        return {
            "surface_distance": round(surface_distance, 1),
            "direct_distance": round(distance_3d, 1),
            "bearing": round(bearing, 1),
            "direction": direction,
        }

    @staticmethod
    async def _fmt_local(utc_dt: dt.datetime, tz_name: Optional[str]) -> str:
        if not tz_name:
            return ""
        try:
            loc = utc_dt.astimezone(ZoneInfo(tz_name))
            return f" / {loc.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name})"
        except Exception:
            return ""

    @staticmethod
    async def _fmt_dur(seconds: int) -> str:
        m, s = divmod(max(0, int(seconds)), 60)
        return f"{m} мин {s} сек" if m else f"{s} сек"

    @staticmethod
    async def _get_country_by_coords(lat: float, lon: float) -> Optional[str]:
        try:
            r = await HTTP.get(SpaceHandler.REV, params={"latitude": lat, "longitude": lon, "language": "ru"}, timeout=6)
            if r.status_code == 200:
                res = (r.json().get("results") or [])
                if res:
                    return res[0].get("country") or None
        except Exception:
            pass
        return None

    @staticmethod
    async def format_passes(
        label: str,
        passes: List[Tuple[dt.datetime, int]],
        now_iss: Optional[Tuple[float, float, dt.datetime]],
        tz_name: Optional[str],
        user_coords: Optional[Tuple[float, float]] = None,
    ) -> str:
        lines: List[str] = []
        lines.append(await SpaceHandler.get_iss_orbital_info())
        lines += [f"📍 <b>Локация: {label}</b>", "🕐 <b>Ближайшие пролёты:</b>"]

        if not passes:
            lines.append("— нет данных —")
        else:
            for i, (rise_utc, dur) in enumerate(passes, 1):
                hour = rise_utc.hour
                if 6 <= hour < 12:
                    time_emoji = "🌅"
                elif 12 <= hour < 18:
                    time_emoji = "☀️"
                elif 18 <= hour < 22:
                    time_emoji = "🌆"
                else:
                    time_emoji = "🌙"
                loc = await SpaceHandler._fmt_local(rise_utc, tz_name)
                lines.append(f"{time_emoji} {i}. {rise_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC{loc}")
                lines.append(f"   ⏱️ Длительность: {await SpaceHandler._fmt_dur(dur)}")

        if now_iss:
            lat, lon, ts = now_iss
            loc_now = await SpaceHandler._fmt_local(ts, tz_name)
            lines += [
                "",
                "🚀 <b>Сейчас МКС:</b>",
                f"📍 Координаты: {lat:.2f}°, {lon:.2f}°",
                f"🕐 Время: {ts.strftime('%Y-%m-%d %H:%M:%S')} UTC{loc_now}",
            ]

            if user_coords:
                user_lat, user_lon = user_coords
                det = await SpaceHandler.get_iss_detailed_info()
                altitude = float(det.get("altitude", 408.0)) if det else 408.0
                if det:
                    velocity = float(det.get("velocity", 27600.0))
                    vis = det.get("visibility", "unknown")
                    lines.append(f"🔭 Высота: {altitude:.1f} км")
                    lines.append(f"💫 Скорость: {velocity:.0f} км/ч")
                    if vis != "unknown":
                        vis_emoji = "☀️" if vis == "daylight" else ("🌙" if vis == "eclipsed" else "🌅")
                        vis_text = "на солнце" if vis == "daylight" else ("в тени Земли" if vis == "eclipsed" else "на границе дня/ночи")
                        lines.append(f"{vis_emoji} Освещение: {vis_text}")

                dist = await SpaceHandler.calculate_distance_to_iss(user_lat, user_lon, lat, lon, altitude)
                lines.append(f"📏 Расстояние: {dist['direct_distance']} км")
                lines.append(f"🧭 Направление: {dist['direction']} ({dist['bearing']}°)")

            country = await SpaceHandler._get_country_by_coords(lat, lon)
            if country:
                lines.append(f"🌍 Сейчас над: {country}")

        return "\n".join(lines)

    async def get_space_report_by_city(self, city: str) -> str:
        geo = await self.geocode_city(city)
        if not geo:
            return "Не нашёл такой город. Попробуйте ещё раз (пример: «Минск»)."

        lat, lon, label, tz = geo
        passes = await self.iss_passes(lat, lon, n=3)
        if not passes:
            return f"⚠️ Сервис пролетов МКС временно недоступен для города «{label}». Попробуйте позже."

        now_iss = self.iss_now()
        return await self.format_passes(label, passes, now_iss, tz, (lat, lon))

    async def get_space_report_by_coords(self, lat: float, lon: float) -> str:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return "Неверные координаты: широта [-90..90], долгота [-180..180]."

        tz = await self._reverse_timezone(lat, lon)
        label = f"{lat:.4f}, {lon:.4f}"
        passes = self.iss_passes(lat, lon, n=3)
        if not passes:
            return f"⚠️ Сервис пролетов МКС временно недоступен для координат {label}. Попробуйте позже."

        now_iss = await self.iss_now()
        return await self.format_passes(label, passes, now_iss, tz, (lat, lon))