
"""
Telegram-бот: отсчёт до Нового года + видео из GitHub.

Установка:
    pip install aiogram aiohttp aiohttp-socks

Переменная окружения:
    BOT_TOKEN

GitHub:
    https://github.com/minecraftbedrock07-ship-it/bot

Видео:
    videos/47.mp4
    videos/48.mp4
    videos/49.mp4
    ...

Рассылка:
    ежедневно в 00:00 по Москве.
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
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.types import BotCommand, Message, FSInputFile


# ───────────────────── НАСТРОЙКИ ─────────────────────

TOKEN = os.getenv("BOT_TOKEN", "9269484019:AAEZAFQ-BtT0Ncct2Vu9-UiczMrlBD720Hg")

HAPP_PROXY = "socks5://127.0.0.1:10808"

MSK = timezone(timedelta(hours=3), "MSK")

BASE_DIR = Path(__file__).resolve().parent

CHATS_FILE = BASE_DIR / "chats.json"

# GitHub RAW
GITHUB_VIDEO_URL = (
    "https://raw.githubusercontent.com/"
    "minecraftbedrock07-ship-it/bot/main/videos/"
)

# Временная папка на хостинге.
# Не требуется создавать её вручную.
VIDEO_CACHE = Path(tempfile.gettempdir()) / "newyear_bot_videos"

VIDEO_CACHE.mkdir(
    parents=True,
    exist_ok=True
)


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
        now.year + 1,
        1,
        1,
        0,
        0,
        0,
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
        now.year + 1,
        1,
        1,
        0,
        0,
        0,
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

                result.append(
                    (chat_id, thread_id)
                )

            else:

                result.append(
                    (int(item), None)
                )

        except (ValueError, TypeError, KeyError):

            log.warning(
                "Некорректная запись чата: %s",
                item
            )

    return result


def save_chats(pairs):
    data = []

    for chat_id, thread_id in sorted(
        pairs,
        key=lambda p: (p[0], p[1] or 0)
    ):

        item = {
            "chat_id": chat_id
        }

        if thread_id is not None:

            item["thread_id"] = thread_id

        data.append(item)

    CHATS_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
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

        log.warning(
            "Не удалось сохранить чаты: %s",
            exc
        )


# ───────────────────── GITHUB ВИДЕО ──────────────────

async def download_video(days):
    """
    Скачивает видео с GitHub RAW.

    Если ролик уже скачан, использует локальную копию.
    """

    video_path = VIDEO_CACHE / f"{days}.mp4"

    # Уже скачанный файл
    if video_path.exists():

        if video_path.stat().st_size > 0:

            return video_path

    url = f"{GITHUB_VIDEO_URL}{days}.mp4"

    log.info(
        "Скачиваю видео из GitHub: %s",
        url
    )

    timeout = aiohttp.ClientTimeout(
        total=180,
        connect=30
    )

    try:

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status == 404:

                    log.warning(
                        "Видео %s.mp4 отсутствует на GitHub",
                        days
                    )

                    return None

                response.raise_for_status()

                # Сохраняем сначала во временный файл,
                # чтобы не оставить неполное видео в кэше.
                temp_path = video_path.with_suffix(".tmp")

                with open(temp_path, "wb") as file:

                    async for chunk in response.content.iter_chunked(
                        1024 * 1024
                    ):

                        file.write(chunk)

                if temp_path.stat().st_size == 0:

                    temp_path.unlink(missing_ok=True)

                    return None

                temp_path.replace(video_path)

                log.info(
                    "Видео скачано: %s",
                    video_path
                )

                return video_path

    except Exception as exc:

        log.warning(
            "Ошибка загрузки видео с GitHub: %s",
        )

        log.warning(
            "%s",
            exc
        )

        return None


# ───────────────────── ОТПРАВКА ──────────────────────

async def send_countdown(message):

    now = datetime.now(MSK)

    days = get_days_left(now)

    text = countdown_text_by_days(
        days,
        now
    )

    video_path = await download_video(days)

    if video_path:

        try:

            await message.answer_video(
                video=FSInputFile(video_path),
                caption=text
            )

            return

        except Exception as exc:

            log.warning(
                "Ошибка отправки видео: %s",
                exc
            )

    await message.answer(text)


# ───────────────────── КОМАНДЫ ──────────────────────

@dp.message(
    Command(
        "start",
        "days",
        "ny",
        "newyear"
    )
)
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


# ───────────────────── РАССЫЛКА ─────────────────────

async def push(bot):

    targets = chats()

    if not targets:

        log.warning(
            "chats.json пуст. Напиши боту /days."
        )

        return

    now = datetime.now(MSK)

    days = get_days_left(now)

    text = countdown_text_by_days(
        days,
        now
    )

    video_path = await download_video(days)

    # Сначала отправляем видео в первый чат.
    # Полученный Telegram file_id используем
    # для остальных чатов.
    uploaded_file_id = None

    for chat_id, thread_id in targets:

        extra = {}

        if thread_id is not None:

            extra["message_thread_id"] = thread_id

        try:

            if video_path:

                if uploaded_file_id:

                    await bot.send_video(
                        chat_id=chat_id,
                        video=uploaded_file_id,
                        caption=text,
                        **extra
                    )

                else:

                    msg = await bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(video_path),
                        caption=text,
                        **extra
                    )

                    if msg.video:

                        uploaded_file_id = (
                            msg.video.file_id
                        )

            else:

                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    **extra
                )

            log.info(
                "Отправлено в чат %s, тема %s",
                chat_id,
                thread_id
            )

        except Exception as exc:

            log.warning(
                "Ошибка отправки в %s: %s",
                chat_id,
                exc
            )


# ───────────────────── РАСПИСАНИЕ ───────────────────

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


async def scheduler(bot):

    log.info(
        "Планировщик запущен. Ожидание 00:00 МСК."
    )

    while True:

        now = datetime.now(MSK)

        target = next_midnight(now)

        seconds = (
            target - now
        ).total_seconds()

        log.info(
            "Следующая рассылка: %s",
            target.strftime("%d.%m.%Y %H:%M")
        )

        await asyncio.sleep(
            max(1, seconds)
        )

        try:

            await push(bot)

        except Exception:

            log.exception(
                "Ошибка автоматической рассылки"
            )


# ───────────────────── ПОДКЛЮЧЕНИЕ ─────────────────

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

        proxy = os.environ[
            "SOCKS_PROXY"
        ].strip()

        return [
            proxy or None
        ]

    parsed = urlparse(HAPP_PROXY)

    host = parsed.hostname or "127.0.0.1"

    port = parsed.port or 10808

    if port_open(host, port):

        return [
            HAPP_PROXY,
            None
        ]

    return [
        None,
        HAPP_PROXY
    ]


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
                    command="days",
                    description="Сколько дней до Нового года"
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
            "Рассылка каждый день в 00:00 МСК."
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

        log.info(
            "Бот остановлен."
        )
