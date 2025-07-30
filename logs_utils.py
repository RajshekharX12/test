#!/usr/bin/env python3
"""
logs_utils.py

“Jarvis logs” DM handler – Top 5 error summary.
"""

import sys
from pathlib import Path
from collections import Counter
from aiogram import F
from aiogram.enums import ChatType

# pull in the real dp
_main = sys.modules["__main__"]
dp   = _main.dp

LOG_FILE = Path(__file__).parent / "bot.log"

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis logs$")
)
async def logs_handler(msg):
    if not LOG_FILE.exists():
        return await msg.reply("⚠️ bot.log not found.")
    lines = LOG_FILE.read_text().splitlines()

    # gather only lines marked ERROR
    errs = []
    for l in lines:
        if " ERROR " in l:
            parts = l.split(" ", 2)
            errs.append(parts[2] if len(parts)==3 else l)

    if not errs:
        return await msg.reply("✅ No ERROR entries in log.")

    cnt = Counter(errs)
    top5 = cnt.most_common(5)
    text = "🔍 Top 5 Errors:\n"
    for i,(m,n) in enumerate(top5,1):
        text += f"{i}. {m} — {n} time{'s' if n>1 else ''}\n"

    await msg.reply(text)
