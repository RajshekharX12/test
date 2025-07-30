#!/usr/bin/env python3
"""
threat.py

Pre‑restart health check plugin.  
Verifies bot.py compiles (and optionally lints) before allowing
“Jarvis restart” to proceed.
"""

import sys
import subprocess
import asyncio
from aiogram import F, types
from aiogram.enums import ChatType

# grab running bot & dispatcher
_main = sys.modules["__main__"]
dp    = _main.dp
bot   = _main.bot

# the original restart handler we defined in bot.py
orig_restart = _main.restart_handler  

def health_check() -> bool:
    """Return True if bot.py syntax (and lint) passes."""
    # 1) Syntax check
    rc = subprocess.run(
        [sys.executable, "-m", "py_compile", "bot.py"]
    ).returncode
    if rc != 0:
        return False

    # 2) (Optional) lint check - uncomment if you have flake8 installed
    # lint = subprocess.run(["flake8", "--max-line-length=120"], capture_output=True)
    # if lint.returncode != 0:
    #     return False

    return True

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis restart$")
)
async def restart_guard(msg: types.Message):
    # 1) run health check in executor
    await msg.reply("🔎 Running pre‑restart health check…")
    ok = await asyncio.get_event_loop().run_in_executor(None, health_check)
    if not ok:
        return await msg.reply("❌ Health check failed! Aborting restart.")
    # 2) delegate to the original restart handler
    await orig_restart(msg)
