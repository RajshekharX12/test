import os
import html
import logging
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from dotenv import load_dotenv

# ─── LOAD CONFIG ───────────────────────────────────────────────
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGER SETUP ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── BOT SETUP ─────────────────────────────────────────────────
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ─── BHAAI HANDLER ─────────────────────────────────────────────
@dp.message(F.text.startswith("bhai"))
async def chatgpt_handler(message: types.Message):
    try:
        # Extract user query
        parts = message.text.split(maxsplit=1)
        query = parts[1] if len(parts) > 1 else None
        if not query and message.reply_to_message:
            query = message.reply_to_message.text
        if not query:
            return await message.reply("❗ Bhai, mujhe question toh de...")

        # Security & abuse check
        if len(query) > 1000:
            return await message.reply("⚠️ Bhai, question zyada lamba ho gaya. Thoda chhota puchho.")

        # Send "Generating..." status
        status = await message.reply("🧠 Generating answer...")

        prompt_intro = (
            "<p>You are user's friend. Reply in friendly Hindi with emojis, "
            "using 'bhai' words like 'Arey bhai', 'Nahi bhai', etc.</p>"
        )
        payload = {
            "message": prompt_intro + html.escape(query),
            "chat_mode": "assistant",
            "dialog_messages": [{"bot": "", "user": ""}]
        }

        # Safone API request
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.safone.dev/chatgpt",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = await resp.json()
            answer = data.get("message")
            if not answer:
                raise ValueError("No 'message' in response")

        # Send final reply
        safe_answer = html.escape(answer)
        text = (
            f"<b>Query:</b>\n~ <i>{html.escape(query)}</i>\n\n"
            f"<b>ChatGPT:</b>\n~ <i>{safe_answer}</i>"
        )
        await status.edit_text(text)

    except httpx.HTTPError as http_err:
        logger.exception("HTTP error from SafoneAPI")
        await message.reply(f"❌ HTTP Error: {http_err}")
    except ValueError as val_err:
        logger.exception("Invalid response format")
        await message.reply(f"⚠️ Response Error: {val_err}")
    except Exception as e:
        logger.exception("Unexpected error")
        await message.reply("🚨 Internal Error occurred. Try again later.")

# ─── COMMAND /start ────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Bhai, mujhe 'bhai &lt;sawal&gt;' likh kar puchho. Main Hindi mein dost jaisa reply dunga!"
    )

# ─── MAIN ──────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Bot is starting...")
    dp.run_polling(bot)




