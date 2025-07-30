#!/usr/bin/env python3
"""
logs_utils.py

• “Jarvis logs” DM handler.
"""

from pathlib import Path
from aiogram import types, F
from aiogram.enums import ChatType, ParseMode
from bot import dp

LOG_FILE = Path("bot.log")

def get_chunks(path: Path, size: int = 4000):
    text = path.read_text() if path.exists() else ""
    return [text[i : i + size] for i in range(0, len(text), size)]

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message) -> None:
    if not LOG_FILE.exists():
        return await msg.reply("⚠️ bot.log not found.")
    chunks = get_chunks(LOG_FILE)
    if not chunks:
        return await msg.reply("⚠️ bot.log is empty.")
    for c in chunks:
        await msg.reply(f"```{c}```", parse_mode=ParseMode.MARKDOWN)
