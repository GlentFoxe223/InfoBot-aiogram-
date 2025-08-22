# app/main.py
import os
import sys
import time
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from loguru import logger
from aiogram.filters.command import Command
from aiogram.filters import CommandStart
from aiogram import Bot, Dispatcher, types, F
from aiogram import fsm
import asyncio
import html as thtml

if getattr(sys, "frozen", False):
    application_path = Path(sys.executable).parent
else:
    application_path = Path(__file__).parent.parent

env_path = application_path / ".env"

load_dotenv(dotenv_path=env_path, override=True)
BOT_TOKEN = os.getenv("BOT_API1")

if not BOT_TOKEN:
    print("Ошибка: не найден .env или переменная BOT_API1")
    print(f"Искали .env в: {env_path} (exists={env_path.exists()})")
    if env_path.exists():
        for line in (env_path.read_text(encoding="utf-8").splitlines()):
            if line.strip() and not line.startswith("#") and "=" in line:
                print(f"  {line.split('=',1)[0]}=***")
    raise RuntimeError("Переменная BOT_API1 не задана")

LOG_DIR = application_path / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

logger.remove()

logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    enqueue=True,
    backtrace=True,
    diagnose=False,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
           "<level>{level: <7}</level> | "
           "{extra[feature]: <8} | "
           "{message}",
)

if os.getenv("LOG_TO_FILES", "1") == "1":
    def _by_feature(name: str):
        return lambda rec: rec["extra"].get("feature") == name

    for feat in ("core", "weather", "space", "news", "ii", "errors", "tg"):
        feat_dir = LOG_DIR / feat
        feat_dir.mkdir(parents=True, exist_ok=True)
        log_path = feat_dir / (f"{feat}" + "_{time}.log")
        logger.add(
            log_path,
            rotation="5 MB",
            retention="7 days",
            compression="zip",
            level="DEBUG",
            enqueue=True,
            filter=_by_feature(feat),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {message}",
        )

def _excepthook(exctype, value, tb):
    logger.bind(feature="errors").opt(exception=(exctype, value, tb)).error("Unhandled exception")
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = _excepthook

def log_action(msg: str, *, feature: str = "core", **extra):
    logger.bind(feature=feature, **extra).info(msg)

def trace(name: Optional[str] = None, *, feature: str = "core"):
    def deco(fn: Callable):
        tag = name or fn.__name__
        @wraps(fn)
        def wrap(*args, **kwargs):
            t0 = time.perf_counter()
            logger.bind(feature=feature).debug(f"{tag}: ENTER args={_short(args)} kwargs={_short(kwargs)}")
            try:
                res = fn(*args, **kwargs)
                dt = (time.perf_counter() - t0) * 1000
                logger.bind(feature=feature).debug(f"{tag}: OK in {dt:.1f} ms -> {_short(res)}")
                return res
            except Exception as e:
                dt = (time.perf_counter() - t0) * 1000
                logger.bind(feature="errors").exception(f"{tag}: FAIL in {dt:.1f} ms err={e}")
                raise
        return wrap
    return deco

def _short(x: Any, maxlen: int = 240) -> str:
    s = repr(x)
    return s if len(s) <= maxlen else s[:maxlen] + "…"

async def log_msg(prefix: str, m: types.Message, *, feature: str = "tg"):
    fu = getattr(m, "from_user", None)
    ch = getattr(m, "chat", None)
    logger.bind(feature=feature).info(
        f"{prefix}: uid={getattr(fu,'id',None)} @{getattr(fu,'username',None)} "
        f"cid={getattr(ch,'id',None)} mid={getattr(m,'message_id',None)} "
        f"type={m.content_type} text={_short((m.text or '').strip())}"
    )

async def send_message_logged(bot: Bot, message: types.Message, text: str, **kw) -> types.Message:
    logger.bind(feature="tg").debug(f"send_message(chat_id={message}, len={len(text)}, keys={list(kw.keys())})")
    msg = await message.answer(text, **kw)
    logger.bind(feature="tg").info(f"sent_message: chat_id={message} mid={msg.message_id}")
    return msg

async def send_photo_logged(bot: Bot, message: types.Message, **kw) -> types.Message:
    logger.bind(feature="tg").debug(f"send_photo(chat_id={message}, keys={list(kw.keys())})")
    msg = await message.answer_photo(**kw)
    logger.bind(feature="tg").info(f"sent_photo: chat_id={message} mid={msg.message_id}")
    return msg

async def register_next_step_logged(bot: Bot, msg: types.Message, handler: Callable):
    logger.bind(feature="tg").debug(
        f"register_next_step(chat_id={msg.chat.id}, wait_mid={msg.message_id}, handler={handler.__name__})"
    )
    await fsm(msg, handler)

async def _resolve_image_path(image_name: str) -> Optional[Path]:
    candidates = [
        application_path / "static" / "images" / image_name,
        application_path / "app" / "static" / "images" / image_name,
        Path(__file__).parent / "static" / "images" / image_name,
        Path.cwd() / "static" / "images" / image_name,
    ]
    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return None

bot = Bot(token=BOT_TOKEN)
dp=Dispatcher()

sys.path.insert(0, str(application_path))
sys.path.insert(0, str(application_path / "app"))
log_action("sys.path updated", feature="core", path_list=sys.path[:4])

from app.db.DBsearcher import DBsearcher
from app.handlers.WeatherHandler import WeatherHandler
from app.handlers.NewsHandler import NewsHandler
from app.handlers.IIHandler import IIHandler
from app.handlers.SpaceHandler import SpaceHandler
from app.utils.helpers import Cleaner, Player

MENU: tuple[str, ...] = ("Погода", "Космос", "Новости", "ИИ помощник")
NAV: tuple[str, ...] = ("Далее", "Назад")

def mk_kb(*rows):
    keyboard = [[types.KeyboardButton(text=x) for x in row] for row in rows]
    return types.ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )

MAIN_KB = mk_kb(MENU[:2], MENU[2:])
log_action("MAIN_KB built", feature="core", rows=MENU)

class BotCore:
    @trace("BotCore.__init__", feature="core")
    def __init__(self):
        db_path = application_path / "botdata.db"
        self.db = DBsearcher(str(db_path))

        self.main_kb = MAIN_KB
        self.remove_kb = types.ReplyKeyboardRemove()
        self.user_pages: dict[int, dict] = {}
        self.user_data: dict[int, dict] = {}

        self.space = SpaceHandler()

        self.proxy_address = os.getenv("proxy_address")
        self.proxy_username = os.getenv("proxy_username")
        self.proxy_password = os.getenv("proxy_password")
        self.proxies = {
            "http": f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_address}"
            if self.proxy_address and self.proxy_username and self.proxy_password else None,
            "https": f"http://{self.proxy_username}:{self.proxy_password}@{self.proxy_address}"
            if self.proxy_address and self.proxy_username and self.proxy_password else None,
        }
        self.headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/91.0.4472.124 Safari/537.36")
        }

        log_action("BotCore initialized",
                   feature="core",
                   db=str(db_path),
                   env=str(env_path),
                   proxies_enabled=bool(self.proxies["http"] or self.proxies["https"]))

    @trace(feature="core")
    async def route_if_menu(self,message: types.Message) -> bool:
        txt =(getattr(message, "text", "") or "").strip()
        if not txt:
            log_action("route_if_menu: empty text", feature="core")
            return False
        if txt in (*MENU, *NAV):
            log_action("Route menu", feature="core", txt=txt, uid=message.from_user.id, cid=message.chat.id)
            if txt == "Погода":
                return self._go_weather(message)
            if txt == "Космос":
                return self._go_space(message)
            if txt == "Новости":
                return self._go_news(message)
            if txt == "ИИ помощник":
                return self._go_ii(message)
            if txt == "Назад":
                await send_message_logged(bot, message, "Возвращаемся в главное меню:", reply_markup=self.main_kb)
                return True
        return False

    @trace(feature="weather")
    async def _go_weather(self, message: types.Message) -> bool:
        log_msg("go_weather", message)
        msg = await send_message_logged(bot, message, "Введите город:", reply_markup=self.remove_kb)
        await register_next_step_logged(bot, msg, self.process_weather)
        return True

    @trace(feature="space")
    async def _go_space(self, message: types.Message) -> bool:
        log_msg("go_space", message)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(types.KeyboardButton("Отправить локацию", request_location=True))
        kb.add(types.KeyboardButton("Назад"))
        msg = await send_message_logged(
            bot,
            message,
            "Космос 🚀\nПришлите город текстом или нажмите «Отправить локацию».",
            reply_markup=kb
        )
        await register_next_step_logged(bot, msg, self.process_space_city)
        return True

    @trace(feature="news")
    async def _go_news(self, message: types.Message) -> bool:
        log_msg("go_news", message)
        user_id = message.from_user.id
        parser = NewsHandler()
        news = parser.get_news()
        log_action("news fetched", feature="news", count=len(news) if news else 0)
        if not news:
            await send_message_logged(bot, message.chat.id, "Не удалось получить новости.", reply_markup=self.main_kb)
            return True
        self.user_pages[user_id] = {"news": news, "page": 0}
        await self.send_news_page(message.chat.id, user_id)
        return True

    @trace(feature="ii")
    async def _go_ii(self, message) -> bool:
        log_msg("go_ii", message)
        ii_kb = mk_kb(("Назад",),)
        msg = await send_message_logged(bot, message.chat.id, "Начните диалог с ИИ. Память отключена.", reply_markup=ii_kb)
        await register_next_step_logged(bot, msg, self.process_II)
        return True

    @trace(feature="core")
    async def register_handlers(self):
        @dp.message(CommandStart())
        async def cmd_start(message: types.Message):
            log_msg("/start", message)
            self.db.add_user(message.from_user.id, message.from_user.username)
            log_action("user added", feature="core", uid=message.from_user.id, uname=message.from_user.username)
            await send_message_logged(bot, message.chat.id, "Привет! Выберите действие:", reply_markup=self.main_kb)

        @dp.message(F.text == "Погода")
        async def cmd_weather(message: types.Message):
            log_msg("btn:Погода", message)
            await self._go_weather(message)

        @dp.message(F.text == "Космос")
        async def cmd_space(message: types.Message):
            log_msg("btn:Космос", message)
            await self._go_space(message)

        @dp.message(F.text == "Новости")
        async def cmd_news(message: types.Message):
            log_msg("btn:Новости", message)
            await self._go_news(message)

        @dp.message(F.text == "Далее" or "Назад")
        async def news_navigation(message: types.Message):
            log_msg("news_nav", message)
            user_id = message.from_user.id
            if user_id not in self.user_pages:
                await send_message_logged(bot, message.chat.id, "Сначала выберите раздел", reply_markup=self.main_kb)
                return
            total_news = len(self.user_pages[user_id]["news"])
            total_pages = (total_news + 9) // 10
            log_action("news_nav_state", feature="news", total=total_news, pages=total_pages,
                       cur=self.user_pages[user_id]["page"])
            if message.text == "Далее":
                cur = self.user_pages[user_id]["page"]
                if cur < total_pages - 1:
                    self.user_pages[user_id]["page"] = cur + 1
                log_action("News next", feature="news", uid=user_id, page=self.user_pages[user_id]["page"])
                self.send_news_page(message.chat.id, user_id)
            elif message.text == "Назад":
                log_action("News back", feature="news", uid=user_id)
                self.user_pages.pop(user_id, None)
                await send_message_logged(bot, message.chat.id, "Возвращаемся в главное меню:", reply_markup=self.main_kb)

        @dp.message(F.text == "ИИ помощник")
        async def cmd_ii(message: types.Message):
            log_msg("btn:ИИ", message)
            await self._go_ii(message)

        @dp.message(F.location)
        async def handle_location(message: types.Message):
            log_msg("location", message)
            await self.process_space_location(message)

        @dp.callback_query(F.text)
        async def handle_article_callback(call: types.CallbackQuery):
            try:
                idx = int(call.data[1:]) - 1
                user_id = call.from_user.id
                news_list = self.user_pages.get(user_id, {}).get("news", [])
                log_action("article_callback", feature="news", idx=idx, available=len(news_list))
                if 0 <= idx < len(news_list):
                    await call.message.answer("Открываю статью…")
                    await self.send_full_page(call.message.chat.id, news_list[idx]["link"])
                else:
                    await call.message.answer("Статья недоступна.")
            except Exception as e:
                await call.message.answer("Ошибка открытия статьи.")
                logger.bind(feature="errors").exception(f"Article callback error: {e}")

    @trace(feature="weather")
    async def process_weather(self, message: types.Message):
        log_msg("process_weather", message)
        if self.route_if_menu(message):
            return
        city = (message.text or "").strip()
        if not city:
            await send_message_logged(bot, message.chat.id, "Введите корректное название города.", reply_markup=self.main_kb)
            return
        weather = WeatherHandler().get_weather(city)
        log_action("weather_received", feature="weather", keys=list(weather.keys()))
        image_name = weather.get("image", "error.png")
        image_path = await _resolve_image_path(image_name)
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    await send_photo_logged(bot, message.chat.id, photo=f)
            except Exception as e:
                logger.bind(feature="errors").exception(f"Send weather image error: {e}")
        else:
            logger.bind(feature="weather").warning(f"Weather image not found: {image_name}")
        await send_message_logged(bot, message.chat.id, weather.get("temp", "Не удалось получить погоду"),
                            reply_markup=self.main_kb)

    @trace(feature="news")
    async def send_news_page(self, chat_id, user_id):
        page_data = self.user_pages[user_id]
        news = page_data["news"]
        page = page_data["page"]
        start, end = page * 10, page * 10 + 10
        news_page = news[start:end]
        log_action("news_page", feature="news", uid=user_id, page=page, start=start, end=end, total=len(news))
        if not news_page:
            await send_message_logged(chat_id=chat_id, bot=bot, text="Новостей больше нет.", reply_markup=self.main_kb)
            self.user_pages.pop(user_id, None)
            return
        total_news = len(news)
        for idx, item in enumerate(news_page, start=start + 1):
            title = item.get("title") or "Без заголовка"
            photo = item.get("photo_link")
            if photo:
                try:
                    await send_photo_logged(bot, chat_id, photo=photo)
                except Exception as e:
                    logger.bind(feature="errors").exception(f"Send news photo error: {e}")
            markup =types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Читать статью", callback_data=f"n{idx}"))
            await send_message_logged(bot, chat_id, f"{idx}. {title}", reply_markup=markup)
        if end >= total_news:
            await send_message_logged(bot, chat_id, "Новостей на сегодня больше нет.", reply_markup=self.main_kb)
            self.user_pages.pop(user_id, None)
        else:
            news_kb = mk_kb(("Далее", "Назад"))
            await send_message_logged(bot, chat_id, "Хотите ещё новостей?", reply_markup=news_kb)

    @trace(feature="news")
    async def send_full_page(self, chat_id, news_url):
        log_action("fetch_full_article", feature="news", url=news_url)
        parser =NewsHandler()
        article =parser.get_deep_news(news_url)
        text = "\n\n".join(article.get("title", []))
        cleaner =Cleaner()
        text = thtml.unescape(cleaner.clean_words(text))
        await send_message_logged(bot, chat_id, (text[:4093] + "...") if len(text) > 4096 else text,
                            reply_markup=self.main_kb)
        for img_url in article.get("images", []):
            try:
                await send_photo_logged(bot, chat_id, photo=img_url)
            except Exception as e:
                logger.bind(feature="errors").exception(f"Send article image error: {e}")
        if "media" in article:
            player = await Player()
            for media_url in article["media"]:
                video_path = None
                try:
                    video_path = await player.download(media_url)
                    size = os.path.getsize(video_path)
                    with open(video_path, "rb") as vf:
                        if size <= 50 * 1024 * 1024:
                            await bot.send_video(chat_id, vf)
                        else:
                            await bot.send_document(chat_id, vf)
                    log_action("media_sent", feature="news", path=video_path, size=size)
                except Exception as e:
                    logger.bind(feature="errors").exception(f"Media send error: {e}")
                finally:
                    if video_path and os.path.exists(video_path):
                        await player.delete(video_path)

    @trace(feature="space")
    async def process_space_city(self, message: types.Message):
        log_msg("process_space_city", message)
        if getattr(message, "location", None):
            return self.process_space_location(message)
        if self.route_if_menu(message):
            return
        city =(message.text or "").strip()
        if not city:
            await send_message_logged(bot, message.chat.id, "Введите город или отправьте локацию.", reply_markup=self.main_kb)
            return
        await send_message_logged(bot, message.chat.id, "Считаю орбиты… 🚀")
        report =self.space.get_space_report_by_city(city)
        log_action("space_report_city_ready", feature="space", city=city, len=len(report))
        await send_message_logged(bot, message.chat.id, report, reply_markup=self.main_kb)

    @trace(feature="space")
    async def process_space_location(self, message):
        log_msg("process_space_location", message)
        loc = getattr(message, "location", None)
        if not loc:
            await send_message_logged(bot, message.chat.id, "Локация не пришла. Попробуйте ещё раз.", reply_markup=self.main_kb)
            return
        await send_message_logged(bot, message.chat.id, "Считаю орбиты… 🚀")
        report = await self.space.get_space_report_by_coords(loc.latitude, loc.longitude)
        log_action("space_report_geo_ready", feature="space",
                   lat=loc.latitude, lon=loc.longitude, len=len(report))
        await send_message_logged(bot, message.chat.id, report, reply_markup=self.main_kb)

    @trace(feature="ii")
    async def process_II(self, message: types.Message):
        log_msg("process_II", message)
        if self.route_if_menu(message):
            return
        text = (message.text or "").strip()
        if not text:
            msg = await send_message_logged(bot, message.chat.id, "Введите текст")
            register_next_step_logged(bot, msg, self.process_II)
            return
        answer = IIHandler().get_answer(text)
        await send_message_logged(bot, message.chat.id, answer, reply_markup=self.main_kb)
        msg = await send_message_logged(bot, message.chat.id, "Продолжайте ✍️")
        register_next_step_logged(bot, msg, self.process_II)

    @trace(feature="core")
    async def run(self):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            log_action("Webhook deleted (drop_pending_updates=True)", feature="tg")
        except Exception as e:
            log_action(f"delete_webhook failed: {e}; try remove_webhook()", feature="tg")
            try:
                bot.remove_webhook()
                log_action("remove_webhook OK", feature="tg")
            except Exception as e2:
                logger.bind(feature="errors").exception(f"remove_webhook FAIL: {e2}")
        await self.register_handlers()
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        log_action("Запуск бота…", feature="core")
        log_action(f"Рабочая директория: {application_path}", feature="core")
        log_action(f"Файл .env: {env_path}", feature="core")
        log_action(f"База данных: {application_path / 'botdata.db'}", feature="core")
        bot_core = BotCore()
        log_action("Start polling", feature="tg", timeout=20, long_polling_timeout=20)
        asyncio.run(bot_core.run())
    except Exception as e:
        logger.bind(feature="errors").exception(f"Ошибка запуска бота: {e}")
        raise