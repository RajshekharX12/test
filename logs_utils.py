#!/usr/bin/env python3
"""
logs_utils.py

• get_log_chunks(path: str, chunk_size: int) -> list[str]
• Registers a private‑chat handler on import for “Jarvis logs”.
"""

from pathlib import Path
from typing import List

from aiogram import types, F
from aiogram.enums import ChatType, ParseMode
from bot import dp  # assumes bot.py defines dp

LOG_PATH = Path("bot.log")

def get_log_chunks(path: str, chunk_size: int = 4000) -> List[str]:
    """Read file and return consecutive chunks of up to `chunk_size` chars."""
    data = Path(path).read_text()
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message) -> None:
    """Stream back bot.log in 4 000‑char slices."""
    if not LOG_PATH.exists():
        return await msg.reply("⚠️ No bot.log file found.")
    chunks = get_log_chunks(str(LOG_PATH))
    if not chunks:
        return await msg.reply("⚠️ bot.log is empty.")
    for chunk in chunks:
        await msg.reply(f"```{chunk}```", parse_mode=ParseMode.MARKDOWN)
