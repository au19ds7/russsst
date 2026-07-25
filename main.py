import asyncio
import json
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from rustplus import RustSocket, FCMListener

logging.basicConfig(level=logging.INFO)

TG_TOKEN = os.environ["TG_TOKEN"]  # берётся из Railway Variables, НЕ из кода
DATA_FILE = "/data/user_data.json"

bot = Bot(TG_TOKEN)
dp = Dispatcher()


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


user_servers = load_data()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для Rust+.\n\n"
        "/pair — привязать сервер\n"
        "/status — статус сервера"
    )


@dp.message(Command("pair"))
async def cmd_pair(message: types.Message):
    tg_id = message.from_user.id

    creds = await FCMListener.register()
    with open(f"/data/fcm_{tg_id}.json", "w") as f:
        json.dump(creds.as_dict(), f)

    await message.answer(
        "1️⃣ Открой ссылку и войди через Steam:\n"
        f"{creds.pairing_url}\n\n"
        "2️⃣ В приложении Rust+ выбери сервер и нажми Pair."
    )

    async def on_pair(notification):
        try:
            body = json.loads(notification["data"]["body"])
            if body.get("type") == "server":
                user_servers[str(tg_id)] = {
                    "ip": body["ip"],
                    "port": body["port"],
                    "playerId": body["playerId"],
                    "playerToken": body["playerToken"],
                }
                save_data(user_servers)
                await bot.send_message(tg_id, f"✅ Привязано: {body['ip']}:{body['port']}")
        except Exception as e:
            logging.exception(e)

    listener = FCMListener(creds, on_pair)
    asyncio.create_task(listener.listen())


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    tg_id = str(message.from_user.id)
    data = user_servers.get(tg_id)
    if not data:
        await message.answer("Сначала выполни /pair")
        return

    try:
        socket = RustSocket(data["ip"], data["port"], data["playerId"], data["playerToken"])
        await socket.connect()
        info = await socket.get_info()
        await socket.disconnect()
        await message.answer(
            f"🏠 {info.name}\n👥 {info.players}/{info.max_players}\n⏰ Wipe: {info.wipe_time}"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
