
"""
Telegram-бот: обратный отсчёт до Нового года + ежедневные видео.

Установка:
    pip install aiogram aiohttp aiohttp-socks

Переменная окружения:
    BOT_TOKEN

Владелец:
    OWNER_ID — твой Telegram ID.

GitHub:
    https://github.com/minecraftbedrock07-ship-it/bot

Видео:
    videos/47.mp4
    videos/48.mp4
    videos/49.mp4
    ...

Рассылка:
    ежедневно в 00:00 по Москве.

Команды:
/start      - обратный отсчёт + видео
/days       - обратный отсчёт + видео
/ny         - обратный отсчёт + видео
/newyear    - обратный отсчёт + видео
/video      - видео текущего дня (только владелец)
/video 47   - видео 47-го дня (только владелец)
"""

import asyncio
import json
import logging
import os
import socket
import tempfile

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Message, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command


# ───────────────────── НАСТРОЙКИ ─────────────────────

TOKEN = os.getenv("BOT_TOKEN", "9269484019:AAEZAFQ-BtT0Ncct2Vu9-UiczMrlBD720Hg")

OWNER_ID = 1377920047

HAPP_PROXY = "socks5://127.0.0.1:10808"

MSK = timezone(timedelta(hours=3), "MSK")

BASE_DIR = Path(__file__).resolve().parent

CHATS_FILE = BASE_DIR / "chats.json"

GITHUB_VIDEO_URL = (
    "https://raw.githubusercontent.com/"
    "minecraftbedrock07-ship-it/new_year/main/videos/"
)

VIDEO_CACHE = Path(tempfile.gettempdir()) / "newyear_bot_videos"
VIDEO_CACHE.mkdir(parents=True, exist_ok=True)


# ───────────────────── ЛОГИ ──────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("newyear")

dp = Dispatcher()


# ───────────────────── ОТСЧЁТ ────────────────────────

def plural(number, one, few, many):
    n = abs(number) % 100

    if 11 <= n <= 14:
        return many

    n %= 10

    if n == 1:
        return one

    if 2 <= n <= 4:
        return few

    return many


def get_days_left(now=None):
    now = now or datetime.now(MSK)

    target = datetime(
        now.year + 1, 1, 1,
        0, 0, 0,
        tzinfo=MSK
    )

    seconds = max(
        0,
        int((target - now).total_seconds())
    )

    return seconds // 86400


def countdown_text_by_days(days, now=None):
    now = now or datetime.now(MSK)

    target = datetime(
        now.year + 1, 1, 1,
        0, 0, 0,
        tzinfo=MSK
    )

    total = max(
        0,
        int((target - now).total_seconds())
    )

    hours_total, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    hours = hours_total % 24

    if days == 0:

        if hours_total == 0:
            left = f"{minutes} мин {seconds} с"

        else:
            left = (
                f"{hours_total} ч "
                f"{minutes} мин "
                f"{seconds} с"
            )

    else:

        left = (
            f"{days} д "
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    return (
        f"🎄 <b>До Нового года {target.year} осталось</b>\n\n"
        f"🎁 <b>{days} "
        f"{plural(days, 'день', 'дня', 'дней')}</b>\n\n"
        f"📅 {target:%d.%m.%Y}\n"
        f"⏱ {left}"
    )


# ───────────────────── ЧАТЫ ──────────────────────────

def chats():

    try:
        raw = json.loads(
            CHATS_FILE.read_text(encoding="utf-8")
        )

    except (OSError, ValueError):
        return []

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:

        try:

            if isinstance(item, dict):

                chat_id = int(item["chat_id"])

                thread = item.get("thread_id")

                thread_id = (
                    int(thread)
                    if thread is not None
                    else None
                )

                result.append((chat_id, thread_id))

            else:
                result.append((int(item), None))

        except (ValueError, TypeError, KeyError):
            log.warning("Некорректная запись чата: %s", item)

    return result


def save_chats(pairs):

    data = []

    for chat_id, thread_id in sorted(
        pairs,
        key=lambda p: (p[0], p[1] or 0)
    ):

        item = {"chat_id": chat_id}

        if thread_id is not None:
            item["thread_id"] = thread_id

        data.append(item)

    CHATS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def remember(chat_id, thread_id=None):

    try:

        known = set(chats())
        pair = (chat_id, thread_id)

        if pair not in known:

            known.add(pair)
            save_chats(known)

            log.info(
                "Сохранён чат %s, тема %s",
                chat_id,
                thread_id
            )

    except OSError as exc:
        log.warning("Не удалось сохранить чаты: %s", exc)

# ───────────────────── СКАЧИВАНИЕ ВИДЕО ───────────────

async def download_video(day: int):
    filename = f"{day}.mp4"
    cached_path = VIDEO_CACHE / filename

    if cached_path.exists() and cached_path.stat().st_size > 0:
        return cached_path

    url = GITHUB_VIDEO_URL + filename

    try:
        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                log.info("ЗАПРОС ВИДЕО: %s", url)
                log.info("ОТВЕТ GITHUB: HTTP %s", response.status)
                if response.status == 404:
                    log.warning("Видео %s не найдено", filename)
                    return None

                response.raise_for_status()

                with open(cached_path, "wb") as file:
                    async for chunk in response.content.iter_chunked(65536):
                        file.write(chunk)

        if cached_path.stat().st_size > 0:
            log.info("Видео %s скачано", filename)
            return cached_path

    except Exception:
        log.exception("Ошибка скачивания %s", filename)

        if cached_path.exists():
            cached_path.unlink()

    return None

# ───────────────────── ОТПРАВКА ОТСЧЁТА ───────────────

async def send_countdown(message: Message):

    now = datetime.now(MSK)
    days = get_days_left(now)

    text = countdown_text_by_days(days, now)

    await message.answer(text)

    video_path = await download_video(days)

    if video_path:

        try:
            await message.answer_video(video=FSInputFile(video_path))

        except Exception:
            log.exception("Ошибка отправки видео")


# ───────────────────── КОМАНДЫ ───────────────────────

@dp.message(Command("start", "days", "ny", "newyear"))
async def cmd_days(message: Message):

    log.info(
        "Команда из чата %s, тема %s",
        message.chat.id,
        message.message_thread_id
    )

    await send_countdown(message)

    remember(
        message.chat.id,
        message.message_thread_id
    )


@dp.message(Command("video"))
async def cmd_video(message: Message):

    if message.chat.type != "private":
        await message.answer(
            "Используй команду в личных сообщениях."
        )
        return

    if not message.from_user or message.from_user.id != OWNER_ID:

        await message.answer(
            "У тебя нет доступа к этой команде."
        )
        return

    args = (message.text or "").split()

    if len(args) > 2:

        await message.answer(
            "Использование: /video или /video 47"
        )
        return

    try:

        days = int(args[1]) if len(args) == 2 else get_days_left()

        if days < 0:
            raise ValueError

    except ValueError:

        await message.answer(
            "Использование: /video или /video 47"
        )
        return

    await message.answer(
        f"Загружаю видео {days}.mp4..."
    )

    video_path = await download_video(days)

    if not video_path:

        await message.answer(
            f"Видео {days}.mp4 не найдено на GitHub."
        )
        return

    try:

        await message.answer_video(
            video=FSInputFile(video_path),
            caption=f"Видео за {days}-й день"
        )

        log.info(
            "Владелец запросил видео %s.mp4",
            days
        )

    except Exception:

        log.exception("Ошибка отправки видео")

        await message.answer(
            "Не удалось отправить видео."
        )


# ───────────────────── РАССЫЛКА ───────────────────────

async def push(bot: Bot):

    targets = chats()

    if not targets:

        log.warning(
            "chats.json пуст. Напиши боту /start."
        )
        return

    now = datetime.now(MSK)
    days = get_days_left(now)

    text = countdown_text_by_days(days, now)

    video_path = await download_video(days)

    uploaded_file_id = None

    for chat_id, thread_id in targets:

        extra = {}

        if thread_id is not None:
            extra["message_thread_id"] = thread_id

        try:

            await bot.send_message(
                chat_id=chat_id,
                text=text,
                **extra
            )

            if video_path:

                if uploaded_file_id:

                    await bot.send_video(
                        chat_id=chat_id,
                        video=uploaded_file_id,
                        **extra
                    )

                else:

                    msg = await bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(video_path),
                        **extra
                    )

                    if msg.video:
                        uploaded_file_id = msg.video.file_id

            log.info(
                "Отправлено в чат %s, тема %s",
                chat_id,
                thread_id
            )

        except Exception:

            log.exception(
                "Ошибка отправки в чат %s, тема %s",
                chat_id,
                thread_id
            )


# ───────────────────── РАСПИСАНИЕ ────────────────────

def next_midnight(now=None):

    now = now or datetime.now(MSK)

    target = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    if target <= now:
        target += timedelta(days=1)

    return target


async def scheduler(bot: Bot):

    log.info(
        "Планировщик запущен. Ожидание 00:00 МСК."
    )

    while True:

        now = datetime.now(MSK)
        target = next_midnight(now)

        seconds = (target - now).total_seconds()

        log.info(
            "Следующая рассылка: %s",
            target.strftime("%d.%m.%Y %H:%M")
        )

        await asyncio.sleep(max(1, seconds))

        try:
            await push(bot)

        except Exception:
            log.exception("Ошибка автоматической рассылки")


# ───────────────────── ПОДКЛЮЧЕНИЕ ───────────────────

def port_open(host, port, timeout=2):

    try:

        with socket.create_connection(
            (host, port),
            timeout=timeout
        ):
            return True

    except OSError:
        return False


def proxy_candidates():

    if "SOCKS_PROXY" in os.environ:

        proxy = os.environ["SOCKS_PROXY"].strip()

        return [proxy or None]

    parsed = urlparse(HAPP_PROXY)

    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 10808

    if port_open(host, port):
        return [HAPP_PROXY, None]

    return [None, HAPP_PROXY]


async def connect():

    if not TOKEN:

        raise SystemExit(
            "Не указан BOT_TOKEN в переменных окружения."
        )

    problems = []

    for proxy in proxy_candidates():

        session = (
            AiohttpSession(proxy=proxy)
            if proxy
            else None
        )

        bot = Bot(
            TOKEN,
            session=session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML
            )
        )

        try:

            me = await bot.get_me()

            log.info(
                "Подключился как @%s",
                me.username
            )

            return bot

        except TelegramUnauthorizedError:

            await bot.session.close()

            raise SystemExit(
                "Telegram отверг токен."
            )

        except Exception as exc:

            problems.append(
                f"{proxy or 'без прокси'}: {exc}"
            )

            await bot.session.close()

    raise SystemExit(
        "Не удалось подключиться к Telegram:\n"
        + "\n".join(problems)
    )


# ───────────────────── ЗАПУСК ────────────────────────

async def main():

    bot = await connect()

    try:

        await bot.set_my_commands(
            [
                BotCommand(
                    command="start",
                    description="Запустить бота"
                ),
                BotCommand(
                    command="days",
                    description="Сколько дней до Нового года"
                ),
                BotCommand(
                    command="video",
                    description="Запросить видео (владелец)"
                )
            ]
        )

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        log.info(
            "Бот запущен. Видео берутся с GitHub."
        )

        log.info(
            "Рассылка ежедневно в 00:00 МСК."
        )

        scheduler_task = asyncio.create_task(
            scheduler(bot)
        )

        try:

            await dp.start_polling(bot)

        finally:

            scheduler_task.cancel()

            try:
                await scheduler_task

            except asyncio.CancelledError:
                pass

    finally:
        await bot.session.close()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        log.info("Бот остановлен.")
