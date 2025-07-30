#!/usr/bin/env python3
"""
fragment_url.py

• Inline handler for 888‑prefixed URL generation.
"""

import re
import uuid
from typing import Final

from aiogram import types, F
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from bot import dp, bot

BASE_URL: Final[str] = "https://fragment.com/number/{number}/code"

def format_fragment_url(raw: str) -> str:
    num = re.sub(r"\D", "", raw.strip().lstrip("+"))
    if not num:
        raise ValueError("No digits found")
    if not num.startswith("888"):
        num = "888" + num
    return BASE_URL.format(number=num)

@dp.inline_query(F.query)
async def inline_fragment_handler(inline_q: types.InlineQuery) -> None:
    cleaned = re.sub(r"\D", "", inline_q.query)
    if not cleaned:
        return await bot.answer_inline_query(inline_q.id, results=[], cache_time=0)
    try:
        url = format_fragment_url(cleaned)
    except ValueError:
        return await bot.answer_inline_query(inline_q.id, results=[], cache_time=0)

    article = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title="Fragment check URL",
        description=url,
        input_message_content=InputTextMessageContent(message_text=url)
    )
    await bot.answer_inline_query(inline_q.id, results=[article], cache_time=0)
