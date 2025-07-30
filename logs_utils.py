#!/usr/bin/env python3
"""
logs_utils.py

• get_log_chunks(path: str, chunk_size: int=4000) -> List[str]
• Registers an @dp.message handler on import for “Jarvis logs”.

Usage in bot.py:
    import logs_utils
"""

from pathlib import Path
from typing import List

from aiogram import types, F
from aiogram.enums import ChatType, ParseMode
from bot import dp, bot   # assumes bot.py defines `dp` and `bot`

LOG_PATH = Path("bot.log")

def get_log_chunks(path: str, chunk_size: int = 4000) -> List[str]:
    """Read the entire file at `path` and return 4k‑char chunks."""
    text = Path(path).read_text()
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message) -> None:
    """Send back bot.log in 4000‑char pieces."""
    if not LOG_PATH.exists():
        return await msg.reply("⚠️ No bot.log file found.")
    chunks = get_log_chunks(str(LOG_PATH))
    if not chunks:
        return await msg.reply("⚠️ bot.log is empty.")
    for chunk in chunks:
        await msg.reply(f"```{chunk}```", parse_mode=ParseMode.MARKDOWN)
