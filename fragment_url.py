#!/usr/bin/env python3
"""
fragment_url.py

• format_fragment_url(raw_number: str) -> str  
• Registers an inline query handler on import.
"""

import re
import uuid
from typing import Final

from aiogram import types, F
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

# Import the running Dispatcher & Bot from bot.py
from bot import dp, bot

BASE_URL: Final[str] = "https://fragment.com/number/{number}/code"

def format_fragment_url(raw_number: str) -> str:
    """
    Normalize a phone number and return the Fragment URL.

    1. Strip leading '+' and whitespace
    2. Remove all non‑digits
    3. Prepend '888' if missing
    4. Return "https://fragment.com/number/<num>/code"
    """
    if not isinstance(raw_number, str):
        raise ValueError("Input must be a string")

    num = raw_number.strip().lstrip('+')
    num = re.sub(r"\D", "", num)
    if not num:
        raise ValueError(f"No digits found in {raw_number!r}")

    if not num.startswith("888"):
        num = "888" + num

    return BASE_URL.format(number=num)

@dp.inline_query(F.query)  # only handle non‑empty inline queries
async def inline_fragment_handler(inline_q: types.InlineQuery) -> None:
    """
    Takes any pure‑digit inline query, normalizes it,
    and returns a single InlineQueryResultArticle
    whose content is the Fragment.com URL.
    """
    raw = inline_q.query or ""
    cleaned = re.sub(r"\D", "", raw)

    if not cleaned:
        # explicitly answer “no results” to avoid Telegram fallback
        return await bot.answer_inline_query(inline_q.id, results=[], cache_time=0)

    try:
        url = format_fragment_url(cleaned)
    except ValueError:
        return await bot.answer_inline_query(inline_q.id, results=[], cache_time=0)

    article = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title="Fragment check URL",
        description=url,
        input_message_content=InputTextMessageContent(
            message_text=url
        )
    )

    await bot.answer_inline_query(
        inline_q.id,
        results=[article],
        cache_time=0
    )
