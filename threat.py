#!/usr/bin/env python3
"""
threat.py

AI‑powered “preflight” guard for Jarvis restart:

1) python -m py_compile bot.py  
2) (optional) flake8 lint  
3) ChatGPT code review  
4) Abort or delegate to original restart
"""

import sys
import os
import re
import glob
import traceback
import py_compile
import subprocess
import asyncio

from aiogram import F, types
from aiogram.enums import ChatType

# grab running objects from bot.py (loaded as __main__)
_main         = sys.modules["__main__"]
dp            = _main.dp
bot           = _main.bot
api           = _main.api
orig_restart  = _main.restart_handler

async def ai_health_check(code_map: dict[str, str]) -> list[str]:
    """
    Ask ChatGPT to find crash‑causing issues in the code.
    Returns a list of bullet‑pointed issues (empty = safe).
    """
    # build a trimmed preview of each file
    parts = []
    for fname, src in code_map.items():
        preview = src if len(src) < 2000 else src[:2000] + "\n...TRUNCATED..."
        parts.append(f"### {fname}\n```python\n{preview}\n```")
    joined = "\n\n".join(parts)

    prompt = (
        "👴 Uncle‑Jarvis here—before I restart, please scan my Python code for any "
        "potential runtime errors, missing imports, or crash‑causing bugs. "
        "List each issue as a bullet point. If everything looks safe, just say "
        "`No issues found.`\n\n" + joined
    )

    try:
        resp = await api.chatgpt(prompt)
        text = getattr(resp, "message", str(resp))
    except Exception as e:
        return [f"AI health‑check failed: {e}"]

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    issues = [l for l in lines if re.match(r"^(\-|\*|\d+\.)\s+", l)]
    if not issues and re.search(r"\bno issues\b", text, re.I):
        return []
    return issues or [text.strip()]

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis restart$")
)
async def guarded_restart(msg: types.Message) -> None:
    """Interceptor that runs syntax, lint and AI checks before restart."""
    await msg.reply("🔎 Running pre‑restart health checks…")

    # 1) Syntax check
    try:
        py_compile.compile("bot.py", doraise=True)
    except Exception:
        err = traceback.format_exc()
        return await msg.reply(
            f"❌ Syntax error in bot.py:\n```{err}```",
            parse_mode="Markdown"
        )

    # 2) Optional lint check (uncomment if flake8 is installed)
    lint_rc = subprocess.run(
        ["flake8", "--max-line-length=120", "bot.py"],
        capture_output=True, text=True
    ).returncode
    if lint_rc != 0:
        lint_out = subprocess.run(
            ["flake8", "--max-line-length=120", "bot.py"],
            capture_output=True, text=True
        ).stderr or subprocess.run(
            ["flake8", "--max-line-length=120", "bot.py"],
            capture_output=True, text=True
        ).stdout
        return await msg.reply(
            f"❌ Lint errors detected:\n```{lint_out}```",
            parse_mode="Markdown"
        )

    # 3) Read all .py files
    code_map = {}
    for path in glob.glob("*.py"):
        try:
            code_map[path] = open(path, encoding="utf-8").read()
        except:
            code_map[path] = ""

    # 4) AI health check
    issues = await ai_health_check(code_map)
    if issues:
        text = "🙅‍♂️ Hold on, Master—I’ve spotted some issues:\n"
        for i, issue in enumerate(issues, 1):
            text += f"{i}. {issue}\n"
        text += "\nPlease fix these before we restart."
        return await msg.reply(text)

    # 5) All clear → delegate to original restart
    await msg.reply("✅ All checks passed—restarting now!")
    await orig_restart(msg)
