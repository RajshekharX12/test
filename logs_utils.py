#!/usr/bin/env python3
"""
logs_utils.py

“Jarvis logs” DM handler – Top 5 real error snippets with context.
"""

import sys
from pathlib import Path
from collections import Counter
import re
from aiogram import F, types
from aiogram.enums import ChatType

# grab dispatcher & bot from the running bot.py
_main    = sys.modules["__main__"]
dp       = _main.dp
LOG_FILE = Path(__file__).parent / "bot.log"

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis logs$")
)
async def logs_handler(msg: types.Message):
    if not LOG_FILE.exists():
        return await msg.reply("⚠️ bot.log not found.")

    lines = LOG_FILE.read_text().splitlines()
    entries = []

    for idx, line in enumerate(lines):
        if "Task exception was never retrieved" in line:
            # grab this line plus the next non-empty line for context
            snippet = line
            # look ahead for the first non-empty line (usually the real error)
            for j in range(idx + 1, min(idx + 8, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("Traceback"):
                    snippet += " | " + next_line
                    break
            entries.append(snippet)

        # also catch any other ERROR lines
        elif " ERROR " in line and "Task exception was never retrieved" not in line:
            # include the first traceback line if exists
            snippet = line
            if idx + 1 < len(lines) and lines[idx+1].startswith("Traceback"):
                snippet += " | " + lines[idx+1].strip()
            entries.append(snippet)

    if not entries:
        return await msg.reply("✅ No ERROR entries in log.")

    # count occurrences
    top5 = Counter(entries).most_common(5)

    resp = ["🔍 Top 5 Errors:"]
    for i, (snip, count) in enumerate(top5, 1):
        # truncate if very long
        display = snip if len(snip) < 200 else snip[:200] + "…"
        resp.append(f"{i}. {display} — {count} time{'s' if count>1 else ''}")

    await msg.reply("\n".join(resp))
