#!/usr/bin/env python3
"""
code_review.py

“Jarvis review code” handler – AI-powered suggestions on your Python files.
"""

import sys
from pathlib import Path
from aiogram import F, types
from aiogram.enums import ChatType

# debug load
print("⚙️ code_review.py loaded")

# Grab dispatcher & API
_main = sys.modules["__main__"]
dp    = _main.dp
api   = _main.api

@dp.message(F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"(?i)^jarvis review code$"))
async def review_code_handler(msg: types.Message):
    # collect all .py in this folder
    root = Path(__file__).parent
    content = ""
    for f in root.glob("*.py"):
        if f.name in ("bot.py", "fragment_url.py", "logs_utils.py", "threat.py", "code_review.py"):
            content += f"\n### {f.name}\n"
            content += f.read_text(encoding="utf-8") + "\n"
    prompt = (
        "You are an expert Python developer and code reviewer.\n"
        "Suggest improvements, best practices, and note any issues in the code below:\n\n"
        f"{content}"
    )
    try:
        resp = await api.chatgpt(prompt)
        suggestions = getattr(resp, "message", str(resp))
    except Exception as e:
        suggestions = f"❌ Code review failed: {e}"

    # chunk and reply
    MAX = 3500
    for i in range(0, len(suggestions), MAX):
        await msg.reply(suggestions[i:i+MAX], parse_mode=None)
