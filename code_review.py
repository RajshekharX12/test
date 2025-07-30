#!/usr/bin/env python3
"""
code_review.py

“Jarvis review code” → AI‑powered code health summary.

• Prints a load message on import.
• Registers a private‑chat handler for “jarvis review code”.
• Reads all .py files in cwd, sends to ChatGPT.
• Parses its response into:
    • Overall “health” percentage
    • Top 3 issues
    • High‑level suggestions
• Replies with a compact, formatted message.
"""

import sys
import glob
import asyncio
from aiogram import F, types
from aiogram.enums import ChatType

# Pull in your bot & dispatcher
_main = sys.modules["__main__"]
dp    = _main.dp
api   = _main.api

print("⚙️ code_review.py loaded")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis review code$")
)
async def review_code_handler(msg: types.Message):
    # 1) Ack
    await msg.reply("🔍 Gathering code for review… this may take a moment.")

    # 2) Load all .py files
    files = glob.glob("*.py")
    if not files:
        return await msg.reply("⚠️ No Python files found to review.")

    combined = ""
    for fn in files:
        try:
            with open(fn, "r", encoding="utf‑8") as f:
                snippet = f.read()
        except Exception:
            snippet = "<couldn't read file>"
        combined += f"\n\n# === {fn} ===\n{snippet}"

    # 3) Ask ChatGPT
    prompt = (
        "You are a senior Python code reviewer.\n"
        "Please analyze the following code snippets for:\n"
        "  1) An overall health score (0-100%)\n"
        "  2) The top 3 most critical issues (with filenames/line numbers)\n"
        "  3) A few high-level suggestions to improve readability, structure, or performance.\n\n"
        f"{combined}\n\n"
        "Provide your answer in JSON with keys: score, issues, suggestions."
    )

    try:
        resp = await api.chatgpt(prompt)
        text = getattr(resp, "message", str(resp))
    except Exception as e:
        return await msg.reply(f"🚨 Review failed: {e}")

    # 4) Attempt to parse JSON-like response
    import json, re
    # crude extraction of JSON block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            data = {}

    # 5) Build a neat reply
    if data.get("score") is not None:
        score = data["score"]
        issues = data.get("issues", [])
        suggs = data.get("suggestions", [])
        reply = [f"✅ Code Health: *{score}%*"]
        if issues:
            reply.append("\n*Top 3 Issues:*")
            for i, it in enumerate(issues[:3], 1):
                reply.append(f"  {i}. {it}")
        if suggs:
            reply.append("\n*Suggestions:*")
            for s in suggs[:3]:
                reply.append(f"  • {s}")
        reply_text = "\n".join(reply)
    else:
        # fallback to raw text
        reply_text = text[:3900]
        if len(text) > 3900:
            reply_text += "\n\n…(truncated)…"

    # 6) Send back
    await msg.reply(reply_text, parse_mode="Markdown")
