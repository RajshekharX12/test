#!/usr/bin/env python3
"""
logs_utils.py

“Jarvis logs” DM handler – last 10 errors + AI root-cause, all in plain text.
"""

import sys
from pathlib import Path
from aiogram import F, types
from aiogram.enums import ChatType

# grab dispatcher & api from bot.py
_main   = sys.modules["__main__"]
dp      = _main.dp
api     = _main.api
LOG_FILE = Path(__file__).parent / "bot.log"

MAX_BLOCKS = 10
MAX_CHARS  = 3500

@dp.message(F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message):
    if not LOG_FILE.exists():
        return await msg.reply("bot.log not found.", parse_mode=None)

    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if "ERROR" in lines[i]:
            chunk = [lines[i]]
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t") or lines[j].startswith("Traceback")):
                chunk.append(lines[j])
                j += 1
            blocks.append("\n".join(chunk))
            i = j
        else:
            i += 1

    if not blocks:
        return await msg.reply("No ERROR entries found in bot.log.", parse_mode=None)

    recent = blocks[-MAX_BLOCKS:]
    joined = "\n\n---\n\n".join(recent)

    prompt = (
        "You are a senior reliability engineer.\n"
        "Here are the last error blocks from the bot:\n\n"
        f"{joined}\n\n"
        "For each, give its root cause in one sentence, "
        "so that fixing it would resolve all related errors. "
        "Return up to 10 numbered causes."
    )

    try:
        resp = await api.chatgpt(prompt)
        analysis = getattr(resp, "message", str(resp))
    except Exception as e:
        return await msg.reply(f"AI analysis failed: {e}", parse_mode=None)

    # chunk and reply in plain text
    for start in range(0, len(analysis), MAX_CHARS):
        await msg.reply(analysis[start:start+MAX_CHARS], parse_mode=None)
