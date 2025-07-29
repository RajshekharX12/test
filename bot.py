import os
import html
import logging
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Text
from aiogram.enums import ParseMode
from httpx import HTTPError

# ─── CONFIGURATION ─────────────────────────────────────────
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
# ───────────────────────────────────────────────────────────

@dp.message(Text(startswith="bhai"))
async def chatgpt_handler(message: types.Message):
    # Extract query from command or reply
    parts = message.text.split(maxsplit=1)
    query = parts[1] if len(parts) > 1 else None
    if not query and message.reply_to_message:
        query = message.reply_to_message.text
    if not query:
        return await message.reply("❗ Bhai, mujhe question toh de...")

    # Show generating message
    status = await message.reply("🧠 Generating answer...")

    # Create SafoneAPI payload
    user_input = html.escape(query)
    prompt_intro = (
        "<p>You are user's friend. Reply in friendly Hindi with emojis, "
        "using 'bhai' words like 'Arey bhai', 'Nahi bhai', etc.</p>"
    )
    payload = {
        "message": prompt_intro + user_input,
        "chat_mode": "assistant",
        "dialog_messages": "[{'bot': '', 'user': ''}]"  # optional: implement real dialog history later
    }

    try:
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
                raise ValueError("❌ No 'message' field in API response.")
    except HTTPError as http_err:
        return await status.edit_text(f"❌ HTTP Error: {http_err}")
    except ValueError as val_err:
        return await status.edit_text(f"⚠️ Response Error: {val_err}")
    except Exception as e:
        return await status.edit_text(f"🚨 Unexpected Error: {e}")

    # Format safely with escaped text
    escaped_answer = html.escape(answer)
    text = (
        f"<b>Query:</b>\n~ <i>{user_input}</i>\n\n"
        f"<b>ChatGPT:</b>\n~ <i>{escaped_answer}</i>"
    )
    await status.edit_text(text)

# ─── START BOT ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is starting...")
    dp.run_polling(bot)

