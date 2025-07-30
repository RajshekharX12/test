#!/usr/bin/env python3
"""
fragment_url.py

• format_fragment_url(raw_number: str) -> str
• Registers an @dp.inline_query handler on import.

Usage in bot.py:
    import fragment_url
"""

import re
import uuid
from typing import Final

from aiogram import types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from bot import dp, bot   # assumes bot.py defines `dp` and `bot`

BASE_URL: Final[str] = "https://fragment.com/number/{number}/code"

def format_fragment_url(raw_number: str) -> str:
    """
    Normalize a phone number and return the Fragment URL.

    1. Strip leading '+'  
    2. Remove non‑digits  
    3. Prepend '888' if missing  
    4. Return https://fragment.com/number/<num>/code  

    Raises ValueError if no digits remain.
    """
    if not isinstance(raw_number, str):
        raise ValueError("Input must be a string")

    num = raw_number.lstrip().lstrip('+')
    num = re.sub(r"\D", "", num)
    if not num:
        raise ValueError(f"No digits found in {raw_number!r}")
    if not num.startswith("888"):
        num = "888" + num
    return BASE_URL.format(number=num)

@dp.inline_query()
async def inline_number_check(inline_q: types.InlineQuery) -> None:
    """Handle pure‑digit inline queries by returning the Fragment URL."""
    raw = inline_q.query or ""
    cleaned = re.sub(r"[ \t]+", "", raw).lstrip('+')
    if not re.fullmatch(r"\d+", cleaned):
        return  # only respond to digit‑only queries

    try:
        url = format_fragment_url(cleaned)
    except ValueError:
        return  # invalid number

    result = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title="Fragment check URL",
        description=url,
        input_message_content=InputTextMessageContent(
            message_text=url
        )
    )
    await bot.answer_inline_query(inline_q.id, results=[result], cache_time=0)
