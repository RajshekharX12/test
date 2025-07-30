#!/usr/bin/env python3
"""
logs_utils.py

“Jarvis logs” DM handler – pinpoint root causes of the last 10 errors.

1. Read bot.log, extract ERROR blocks + tracebacks.
2. Keep only the last 10 occurrences.
3. Ask ChatGPT:
     • “For each error block below, identify its root cause.
        If this cause is fixed, all related errors will be resolved.
        Return a numbered list of up to 10 root causes, each concise.”
4. Send the AI’s list back in plain text, chunked if needed.
"""

import sys
from pathlib import Path
from aiogram import F, types
from aiogram.enums import ChatType

# Grab dispatcher & API client from bot.py
_main    = sys.modules["__main__"]
dp       = _main.dp
api      = _main.api
LOG_FILE = Path(__file__).parent / "bot.log"

MAX_BLOCKS = 10     # analyze last 10 errors
MAX_CHARS  = 3500   # chunk size for replies

@dp.message(F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"(?i)^jarvis logs$"))
async def logs_handler(msg: types.Message):
    if not LOG_FILE.exists():
        return await msg.reply("⚠️ `bot.log` not found.", parse_mode=None)

    # 1) Read and collect ERROR blocks
    raw = LOG_FILE.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(raw):
        if "ERROR" in raw[i]:
            chunk = [raw[i]]
            j = i + 1
            # include traceback lines
            while j < len(raw) and (raw[j].startswith(" ") or raw[j].startswith("\t") or raw[j].startswith("Traceback")):
                chunk.append(raw[j])
                j += 1
            blocks.append("\n".join(chunk))
            i = j
        else:
            i += 1

    if not blocks:
        return await msg.reply("✅ No ERROR entries found in `bot.log`.", parse_mode=None)

    # 2) Keep only the most recent MAX_BLOCKS
    recent = blocks[-MAX_BLOCKS:]
    joined = "\n\n---\n\n".join(recent)

    # 3) Build a prompt for root-cause extraction
    prompt = (
        "You are a senior reliability engineer and Python developer. "
        "Below are the last error log entries from a long-running Telegram bot:\n\n"
        f"{joined}\n\n"
        "For each error block, identify its root cause in one sentence. "
        "Assume that fixing this cause will resolve all related errors. "
        "Return a numbered list (1–10) of root causes only."
    )

    # 4) Send to ChatGPT
    try:
        resp = await api.chatgpt(prompt)
        analysis = getattr(resp, "message", str(resp))
    except Exception as e:
        return await msg.reply(f"⚠️ Failed to analyze logs: {e}", parse_mode=None)

    # 5) Chunk and reply
    for start in range(0, len(analysis), MAX_CHARS):
        await msg.reply(analysis[start:start+MAX_CHARS], parse_mode=None)
