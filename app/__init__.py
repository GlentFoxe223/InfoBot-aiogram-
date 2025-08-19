from app.handlers import WeatherHandler
from app.handlers import IIHandler
from app.handlers import NewsHandler
from app.handlers.SpaceHandler import SpaceHandler
from .db import DBsearcher as DB    # <-- ИСПРАВЛЕНО
from .utils import helpers          # <-- ИСПРАВЛЕНО

__all__=[
    SpaceHandler,
    WeatherHandler,
    IIHandler,
    NewsHandler,
    DB,
    helpers
]
