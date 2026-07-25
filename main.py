import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web
from rustplus import RustSocket, ServerDetails, FCMListener

import db
import fcm_auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rustplus-bot")

TG_TOKEN = os.environ["TG_TOKEN"]
PUBLIC_URL = os.environ["PUBLIC_URL"]  # напр. https://your-app.up.railway.app (без / на конце)
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(TG_TOKEN)
dp = Dispatcher()

active_listeners: dict[int, "UserFCMListener"] = {}


class UserFCMListener(FCMListener):
    """Один FCM-listener на пользователя, запускается после успешного /link."""

    def __init__(self, tg_id: int, fcm_credentials: dict):
        # FCMListener ожидает data["fcm_credentials"] с ключами,
        # понятными push_receiver.PushReceiver
        super().__init__({
            "fcm_credentials": {
                "keys": {},  # заполняется библиотекой при необходимости
                "gcm": {
                    "androidId": fcm_credentials["android_id"],
                    "securityToken": fcm_credentials["security_token"],
                },
            }
        })
        self.tg_id = tg_id

    def on_notification(self, obj, notification, data_message):
        try:
            import json
            body_raw = notification.get("data", {}).get("body")
            if not body_raw:
                return
            body = json.loads(body_raw)

            if body.get("type") == "server":
                db.save_server(
                    self.tg_id,
                    ip=body["ip"],
                    port=body["port"],
                    player_id=body["playerId"],
                    player_token=body["playerToken"],
                    name=body.get("name", ""),
                )
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(
                        self.tg_id,
                        f"✅ Сервер привязан: {body.get('name', body['ip'])}\n"
                        f"{body['ip']}:{body['port']}",
                    ),
                    loop,
                )
            elif body.get("type") == "alarm":
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(self.tg_id, f"🚨 Тревога: {body.get('title', '')} — {body.get('message', '')}"),
                    loop,
                )
            else:
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(self.tg_id, f"🔔 {body.get('title', 'Уведомление')}: {body.get('message', '')}"),
                    loop,
                )
        except Exception as e:
            log.exception("on_notification error: %s", e)


# ---------------------------------------------------------------------------
# Telegram-команды
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я слежу за твоим Rust-сервером через Rust+.\n\n"
        "/link — привязать Steam-аккаунт\n"
        "/servers — список привязанных серверов\n"
        "/status — статус сервера"
    )


@dp.message(Command("link"))
async def cmd_link(message: types.Message):
    tg_id = message.from_user.id
    await message.answer("⏳ Регистрирую устройство...")

    try:
        device = await asyncio.to_thread(fcm_auth.register_device)
        expo_token = await asyncio.to_thread(fcm_auth.fetch_expo_push_token, device["fcm_token"])
    except Exception as e:
        log.exception(e)
        await message.answer(f"❌ Не удалось зарегистрировать устройство: {e}")
        return

    db.save_pending_link(
        tg_id, device["android_id"], device["security_token"], device["fcm_token"], expo_token
    )

    return_url = f"{PUBLIC_URL}/callback?uid={tg_id}"
    login_url = fcm_auth.build_login_url(return_url)

    await message.answer(
        "1️⃣ Перейди по ссылке и залогинься через Steam:\n"
        f"{login_url}\n\n"
        "2️⃣ После входа тебя перекинет обратно, и я подтвержу привязку здесь.\n"
        "3️⃣ Потом зайди в игру → меню Rust+ → нажми Pair на нужном сервере."
    )


@dp.message(Command("servers"))
async def cmd_servers(message: types.Message):
    rows = db.get_servers(message.from_user.id)
    if not rows:
        await message.answer("Пока нет привязанных серверов. Используй /link, потом Pair в игре.")
        return
    text = "\n".join(f"• {name or ip}:{port}" for ip, port, _, _, name in rows)
    await message.answer(f"🖥 Твои сервера:\n{text}")


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    rows = db.get_servers(message.from_user.id)
    if not rows:
        await message.answer("Нет привязанных серверов. Сначала /link, потом Pair в игре.")
        return

    ip, port, player_id, player_token, name = rows[0]
    server_details = ServerDetails(
        ip=ip, port=port, player_id=int(player_id), player_token=int(player_token)
    )
    socket = RustSocket(server_details)
    try:
        await socket.connect()
        info = await socket.get_info()
        await message.answer(
            f"🏠 {info.name}\n"
            f"👥 {info.players}/{info.max_players}\n"
            f"🗺 {info.map} ({info.size})"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка подключения: {e}")
    finally:
        await socket.disconnect()


# ---------------------------------------------------------------------------
# HTTP callback: сюда Facepunch редиректит после Steam-логина
# ---------------------------------------------------------------------------

async def handle_callback(request: web.Request):
    tg_id = request.query.get("uid")
    steam_token = request.query.get("token")  # имя параметра нужно свериться на живом редиректе

    if not tg_id or not steam_token:
        return web.Response(text="Missing uid or token", status=400)

    tg_id = int(tg_id)
    pending = db.get_pending_link(tg_id)
    if not pending:
        return web.Response(text="No pending link for this user", status=404)

    android_id, security_token, fcm_token, expo_token = pending

    try:
        refreshed_token = await asyncio.to_thread(
            fcm_auth.register_with_companion, steam_token, expo_token
        )
    except Exception as e:
        log.exception(e)
        return web.Response(text=f"Companion registration failed: {e}", status=500)

    fcm_credentials = {
        "android_id": android_id,
        "security_token": security_token,
        "fcm_token": fcm_token,
        "expo_token": expo_token,
    }
    db.save_user(tg_id, fcm_credentials, refreshed_token)

    listener = UserFCMListener(tg_id, fcm_credentials)
    listener.start(daemon=True)
    active_listeners[tg_id] = listener

    asyncio.run_coroutine_threadsafe(
        bot.send_message(tg_id, "✅ Steam-аккаунт привязан! Теперь зайди в игру и нажми Pair на сервере."),
        loop,
    )

    return web.Response(text="Linked! You can close this tab and return to Telegram.")


async def start_web_app():
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("HTTP callback server started on port %s", PORT)


async def restore_listeners():
    """При рестарте бота поднимаем FCM-listener для уже привязанных юзеров."""
    for tg_id, fcm_credentials in db.get_all_users():
        listener = UserFCMListener(tg_id, fcm_credentials)
        listener.start(daemon=True)
        active_listeners[tg_id] = listener
    log.info("Restored %d FCM listeners", len(active_listeners))


loop: asyncio.AbstractEventLoop


async def main():
    global loop
    loop = asyncio.get_running_loop()

    db.init_db()
    await start_web_app()
    await restore_listeners()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
