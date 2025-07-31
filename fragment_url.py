#!/usr/bin/env python3
"""
fragment_url.py

Inline handler: formats any number into a fragment.com URL.
"""

import sys
import re
from aiogram import types, F
from aiogram.enums import ChatType
from pathlib import Path

# Grab bot & dispatcher
_main = sys.modules["__main__"]
dp    = _main.dp
bot   = _main.bot

def format_fragment_url(raw: str) -> str:
    # strip non-digits, remove leading zeros/plus
    num = re.sub(r"\D+", "", raw).lstrip("0")
    if not num.startswith("888"):
        num = "888" + num
    return f"https://fragment.com/number/{num}/code"

@dp.inline_query(F.query.regexp(r".*"))
async def inline_fragment(inl: types.InlineQuery):
    raw = inl.query.strip()
    cleaned = re.sub(r"\s+", "", raw).lstrip("+")
    if not re.fullmatch(r"\d+", cleaned):
        return
    url = format_fragment_url(cleaned)
    result = types.InlineQueryResultArticle(
        id=inl.id,
        title=f"Fragment URL → {cleaned}",
        description=url,
        input_message_content=types.InputTextMessageContent(
            message_text=url
        )
    )
    await bot.answer_inline_query(inl.id, results=[result], cache_time=30)
