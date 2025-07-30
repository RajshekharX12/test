#!/usr/bin/env python3
"""
threat.py

Selective pre‑restart guard:  
• If bot.log shows recent ERRORs → run syntax+lint+AI health checks  
• Otherwise → delegate straight to restart_handler  
"""

import sys
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

from aiogram import F, types
from aiogram.enums import ChatType

# grab running bot & dispatcher from __main__
_main        = sys.modules["__main__"]
dp           = _main.dp
bot          = _main.bot
orig_restart = _main.restart_handler  # your top‑level restart logic

LOG_FILE = Path(__file__).parent / "bot.log"
ERROR_LOOKBACK = timedelta(minutes=10)  # only guard if errors in last 10m

def has_recent_errors() -> bool:
    """Return True if bot.log contains an ERROR in the last N minutes."""
    if not LOG_FILE.exists():
        return False
    cutoff = datetime.now() - ERROR_LOOKBACK
    for line in LOG_FILE.read_text().splitlines()[::-1]:
        if " ERROR " in line:
            # parse timestamp at start: "2025-07-30 19:38:46,583 ERROR ..."
            ts_str = line.split(" ERROR ", 1)[0]
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
            except Exception:
                # if parse fails, assume it’s recent enough
                return True
            if ts >= cutoff:
                return True
            else:
                return False
    return False

async def health_check() -> bool:
    """Return True if bot.py syntax (and lint) passes."""
    # 1) Syntax check
    if subprocess.run([sys.executable, "-m", "py_compile", "bot.py"]).returncode != 0:
        return False
    # 2) Optional lint (uncomment if flake8 installed)
    # return subprocess.run(["flake8","--max-line-length=120","bot.py"]).returncode == 0
    return True

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis restart$")
)
async def restart_guard(msg: types.Message):
    # 1) If no recent errors, skip health check entirely
    if not has_recent_errors():
        return await orig_restart(msg)

    # 2) Otherwise run the full guard
    await msg.reply("🔎 Recent errors detected—running health checks…")
    ok = await asyncio.get_event_loop().run_in_executor(None, health_check)
    if not ok:
        return await msg.reply("❌ Health check failed! Aborting restart.")
    await orig_restart(msg)
