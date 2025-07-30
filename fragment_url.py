#!/usr/bin/env python3
"""
fragment_url.py

Utility to normalize phone numbers into Fragment check‑URL format:

  • Strips any leading '+'  
  • Removes all non‑digit characters  
  • Ensures the number starts with '888' (prepends if not)  
  • Returns: https://fragment.com/number/<normalized>/code  

Includes basic type hints, validation, and a __main__ block with examples.
"""

import re
from typing import Final

BASE_URL: Final[str] = "https://fragment.com/number/{number}/code"


def format_fragment_url(raw_number: str) -> str:
    """
    Given a raw phone number string, normalize and produce the Fragment URL.

    Steps:
      1. Strip leading '+' if present
      2. Remove all non‑digit characters
      3. If result does not start with '888', prepend '888'
      4. Return the formatted URL

    Raises:
      ValueError: if, after cleaning, the string contains no digits.
    """
    if not isinstance(raw_number, str):
        raise ValueError("Input must be a string")

    # 1) Strip leading '+'
    num = raw_number.lstrip().lstrip('+')

    # 2) Remove non‑digits
    num = re.sub(r"\D", "", num)

    if not num:
        raise ValueError(f"No digits found in input: {raw_number!r}")

    # 3) Ensure '888' prefix
    if not num.startswith("888"):
        num = "888" + num

    # 4) Build URL
    return BASE_URL.format(number=num)


if __name__ == "__main__":
    examples = [
        "70204050",
        "7020 4050",
        "+88870204050",
        "8888 4490 7020",
        "",
        "abc",  # invalid
    ]

    for example in examples:
        try:
            url = format_fragment_url(example)
            print(f"{example!r} → {url}")
        except ValueError as e:
            print(f"{example!r} → Error: {e}")
