import os
import logging
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Text

# ─── CONFIG ────────────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment")
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# ────────────────────────────────────────────────────────────────────────────────

@dp.message(Text(startswith="bhai"))
async def chatgpt2(message: types.Message):
    # 1. Extract query
    parts = message.text.split(maxsplit=1)
    query = parts[1] if len(parts) > 1 else None
    if not query and message.reply_to_message:
        query = message.reply_to_message.text
    if not query:
        return await message.reply("Gimme a question to ask from ChatGPT, bhai.")

    # 2. Show “Generating…” status
    status = await message.reply("Generating answer…")

    # 3. Call SafoneAPI
    additional = (
        "<p>You are user's friend. Reply in friendly Hindi with emojis, "
        "addressing me as bhai with words like “Arey bhai”, “Nahi bhai”, etc.</p>"
    )
    payload = {
        "message": additional + query,
        "chat_mode": "assistant",
        "dialog_messages": "[{'bot': '', 'user': ''}]"
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.safone.dev/chatgpt",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("message")
            if not answer:
                raise ValueError("No ‘message’ field in API response")
    except Exception as e:
        return await status.edit_text(f"Error: {e}")

    # 4. Edit with the answer
    text = (
        f"<b>Query:</b>\n~ <i>{query}</i>\n\n"
        f"<b>ChatGPT:</b>\n~ <i>{answer}</i>"
    )
    await status.edit_text(text, parse_mode="HTML")


if __name__ == "__main__":
    print("🚀 Bot is starting…")
    dp.run_polling(bot)

