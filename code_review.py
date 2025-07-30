#!/usr/bin/env python3
"""
code_review.py

“Jarvis review code” plugin — sends your .py files to ChatGPT and returns
a consolidated list of high‑level improvement suggestions.
"""

import sys
import glob
import asyncio
from pathlib import Path

from aiogram import F, types
from aiogram.enums import ChatType

# Grab our bot & SafoneAPI client
_main = sys.modules["__main__"]
dp    = _main.dp
bot   = _main.bot
api   = _main.api

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis review code$")
)
async def code_review_handler(msg: types.Message) -> None:
    await msg.reply("🔍 Gathering code for review…")
    # 1) Read all .py files in the current directory
    code_map = {}
    for path in glob.glob("*.py"):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception:
            text = ""
        # truncate long files to first 1500 chars each
        snippet = text if len(text) < 1500 else text[:1500] + "\n...TRUNCATED..."
        code_map[path] = snippet

    # 2) Build the ChatGPT prompt
    sections = []
    for fname, snippet in code_map.items():
        sections.append(f"### File: {fname}\n```python\n{snippet}\n```")
    joined = "\n\n".join(sections)

    prompt = (
        "You are Jarvis’s senior engineer. Please review the following Python code files and "
        "provide a concise list of high‑level suggestions for improving the codebase. "
        "Focus on readability, error handling, performance, security, and best practices. "
        "Respond as numbered bullet points.\n\n"
        f"{joined}"
    )

    # 3) Send to ChatGPT
    try:
        resp = await api.chatgpt(prompt)
        suggestions = getattr(resp, "message", str(resp))
    except Exception as e:
        return await msg.reply(f"⚠️ Code review failed: {e}")

    # 4) Reply with the suggestions
    await msg.reply(f"🛠️ Code Review Suggestions:\n\n{suggestions}")
