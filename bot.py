# bot.py
import asyncio
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from SafoneAPI import SafoneAPI

load_dotenv()  # load BOT_TOKEN from .env
BOT_TOKEN = os.getenv("BOT_TOKEN")

api = SafoneAPI()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message()
async def gpt_response(message: Message):
    query = message.text
    if not query:
        return await message.answer("❌ Please type something.")
    try:
        res = await api.chatgpt(query)
        await message.answer(res.response)
    except Exception as e:
        await message.answer(f"⚠️ Error: {e}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
