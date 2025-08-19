import os
import json
import requests
from dotenv import load_dotenv
from functools import wraps

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "InfoBot/1.0 "
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
})

def require_weather_api(func):
    """Декоратор: загружает API-ключ погоды и передаёт его в функцию."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        load_dotenv(override=True)
        api_key = os.getenv("weather_API")
        if not api_key:
            return {"temp": "API-ключ погоды не найден", "image": "error.png"}
        return func(*args, api_key=api_key, **kwargs)
    return wrapper


class WeatherHandler:
    _ICON_BY_MAIN = {
        "rain": "rain.png",
        "drizzle": "rain.png",
        "thunderstorm": "rain.png",
        "snow": "clowd.png",
        "clouds": "clowd.png",
        "mist": "clowd.png",
        "haze": "clowd.png",
        "smoke": "clowd.png",
        "dust": "clowd.png",
        "fog": "clowd.png",
        "sand": "clowd.png",
        "ash": "clowd.png",
        "squall": "clowd.png",
        "tornado": "clowd.png",
        "clear": "summer.png",
    }

    @staticmethod
    def _choose_image(data: dict, temp: float) -> str:
        """Подбор картинки: приоритет по погодному состоянию, иначе по температуре."""
        try:
            main = (data.get("weather", [{}])[0].get("main") or "").lower()
        except Exception:
            main = ""
        if main in WeatherHandler._ICON_BY_MAIN:
            return WeatherHandler._ICON_BY_MAIN[main]
        return "summer.png" if float(temp) >= 10 else "clowd.png"

    @staticmethod
    def _emoji_for(main: str) -> str:
        m = (main or "").lower()
        if m in ("rain", "drizzle", "thunderstorm"): return "🌧️"
        if m == "snow": return "❄️"
        if m in ("clouds", "mist", "fog", "haze", "smoke"): return "☁️"
        if m == "clear": return "☀️"
        return "🌤️"

    @staticmethod
    @require_weather_api
    def get_weather(city: str, api_key: str) -> dict:
        """Возвращает словарь: {temp: текст, image: картинка}."""
        try:
            r = SESSION.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric", "lang": "ru"},
                timeout=12,
            )
        except requests.RequestException as e:
            return {"temp": f"Ошибка сети: {e}", "image": "error.png"}

        if r.status_code != 200:
            try:
                err = r.json()
                msg = err.get("message") or f"Код {r.status_code}"
                if r.status_code == 404:
                    return {"temp": f"Город «{city}» не найден.", "image": "error.png"}
                return {"temp": f"Ошибка API: {msg}", "image": "error.png"}
            except Exception:
                return {"temp": f"Ошибка API: код {r.status_code}", "image": "error.png"}

        try:
            data = r.json()
            city_name = data.get("name") or city

            weather0 = (data.get("weather") or [{}])[0]
            main = weather0.get("main", "")
            desc = (weather0.get("description") or "").capitalize()

            main_blk = data.get("main") or {}
            temp = round(float(main_blk.get("temp", 0)))
            feels = round(float(main_blk.get("feels_like", temp)))
            humidity = int(main_blk.get("humidity", 0))

            pressure_hpa = float(main_blk.get("pressure", 0))
            pressure_mmhg = round(pressure_hpa * 0.75006)

            wind = float((data.get("wind") or {}).get("speed", 0.0))

            image = WeatherHandler._choose_image(data, temp)
            emoji = WeatherHandler._emoji_for(main)

            text = (
                f"{emoji} Погода в {city_name}:\n"
                f"• {desc}\n"
                f"• Температура: {temp}°C (ощущается как {feels}°C)\n"
                f"• Ветер: {wind:.1f} м/с\n"
                f"• Влажность: {humidity}%\n"
                f"• Давление: {pressure_mmhg} мм рт. ст."
            )
            return {"temp": text, "image": image}

        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return {"temp": f"Ошибка обработки данных погоды: {e}", "image": "error.png"}
