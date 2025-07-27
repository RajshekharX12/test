# bot.py
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from SafoneAPI import SafoneAPI

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

api = SafoneAPI()
bot = Bot(BOT_TOKEN)
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
