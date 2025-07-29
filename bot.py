import os
import html
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from dotenv import load_dotenv

# ─── LOAD ENV VARIABLES ────────────────────────────────────────
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING SETUP ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ─── BOT INITIALIZATION ────────────────────────────────────────
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
api = SafoneAPI()

# ─── HANDLER: "bhai" COMMAND ───────────────────────────────────
@dp.message(F.text.startswith("bhai"))
async def chatgpt_handler(message: types.Message):
    try:
        # Extract the query
        parts = message.text.split(maxsplit=1)
        query = parts[1] if len(parts) > 1 else None
        if not query and message.reply_to_message:
            query = message.reply_to_message.text
        if not query:
            return await message.reply("❗ Bhai, mujhe question toh de...")

        # Input length check
        if len(query) > 1000:
            return await message.reply("⚠️ Bhai, question zyada lamba ho gaya. Thoda chhota puchho.")

        # Send "typing" message
        status = await message.reply("🧠 Generating answer...")

        # Prepend prompt instructions
        prompt_intro = (
            "You are user's friend. Reply in friendly Hindi with emojis, "
            "using 'bhai' style words like 'Arey bhai', 'Nahi bhai', etc.\n\n"
        )
        full_prompt = prompt_intro + query

        # Get response from SafoneAPI
        response = await api.chatgpt(full_prompt)
        if not response or not response.message:
            raise ValueError("Invalid response from API")

        # Format and send final response
        safe_answer = html.escape(response.message)
        formatted = (
            f"<b>Query:</b>\n~ <i>{html.escape(query)}</i>\n\n"
            f"<b>ChatGPT:</b>\n~ <i>{safe_answer}</i>"
        )
        await status.edit_text(formatted)

    except Exception as e:
        logger.exception("Unexpected error")
        await message.reply("🚨 Error: Safone API failed ya response nahi aaya.")

# ─── /start COMMAND ────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Bhai, mujhe 'bhai &lt;sawal&gt;' likh kar puchho. Main Hindi mein dost jaisa reply dunga!"
    )

# ─── MAIN ENTRY POINT ──────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Bot is starting...")
    dp.run_polling(bot)

