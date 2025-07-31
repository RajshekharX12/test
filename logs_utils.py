#!/usr/bin/env python3
"""
logs_utils.py

“Jarvis logs” – analyze the last 10 errors and extract root causes.
"""

import sys
from pathlib import Path
from aiogram import F, types
from aiogram.enums import ChatType

# Grab dispatcher & API
_main   = sys.modules["__main__"]
dp      = _main.dp
api     = _main.api
LOG     = Path(__file__).parent / "bot.log"

MAX_BLOCKS = 10
MAX_CHARS  = 3500

@dp.message(F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message):
    if not LOG.exists():
        return await msg.reply("bot.log not found.", parse_mode=None)

    lines = LOG.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if "ERROR" in lines[i]:
            chunk = [lines[i]]
            j = i + 1
            while j < len(lines) and (
                lines[j].startswith(" ") or 
                lines[j].startswith("\t") or 
                lines[j].startswith("Traceback")
            ):
                chunk.append(lines[j]); j += 1
            blocks.append("\n".join(chunk))
            i = j
        else:
            i += 1

    if not blocks:
        return await msg.reply("No ERROR entries found.", parse_mode=None)

    recent = blocks[-MAX_BLOCKS:]
    joined = "\n\n---\n\n".join(recent)

    prompt = (
        "You are a senior reliability engineer.\n"
        "Below are the last error entries from a Telegram bot:\n\n"
        f"{joined}\n\n"
        "For each error, give its root cause in one sentence. "
        "Assume fixing it will resolve all related errors. "
        "Return a numbered list up to 10."
    )

    try:
        resp = await api.chatgpt(prompt)
        analysis = getattr(resp, "message", str(resp))
    except Exception as e:
        return await msg.reply(f"AI failed: {e}", parse_mode=None)

    for start in range(0, len(analysis), MAX_CHARS):
        await msg.reply(analysis[start:start+MAX_CHARS], parse_mode=None)
