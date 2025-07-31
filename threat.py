#!/usr/bin/env python3
"""
threat.py

Pre-restart health-check plugin for “Jarvis restart”.
"""

import sys
import subprocess
import asyncio
from aiogram import F, types
from aiogram.enums import ChatType

# Grab bot & handlers
_main        = sys.modules["__main__"]
dp           = _main.dp
bot          = _main.bot
orig_restart = _main.restart_handler

async def health_check() -> bool:
    """Return True if bot.py compiles without syntax errors."""
    rc = subprocess.run([sys.executable, "-m", "py_compile", "bot.py"]).returncode
    return rc == 0

@dp.message(F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_guard(msg: types.Message):
    await msg.reply("🔎 Running pre-restart health check…", parse_mode=None)
    ok = await asyncio.get_event_loop().run_in_executor(None, health_check)
    if not ok:
        return await msg.reply("❌ Health check failed! Aborting restart.", parse_mode=None)
    await orig_restart(msg)
