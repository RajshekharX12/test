import os
import re
import html
import logging
import asyncio
import httpx

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.enums.chat_action import ChatAction
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from dotenv import load_dotenv

# ─── CONFIG ────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ─── BOT SETUP ─────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY CONFIG ─────────────────────────────────────────────
conversation_histories: dict[int, list[dict[str, str]]] = {}
MAX_HISTORY = 20  # Keep the last 20 messages per user

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── HELPERS ───────────────────────────────────────────────────
def normalize_num(token: str) -> str:
    digits = re.sub(r"\D", "", token)
    if not digits.startswith("888"):
        digits = digits.lstrip("0")
        digits = "888" + digits
    return digits

async def fetch_status(num: str) -> str:
    """
    Check fragment.com/number/{num} for status.
    Returns ❌ Restricted if 'restricted' appears,
    ✅ OK if 'Anonymous Number' appears,
    otherwise ❔ Unknown.
    """
    url = f"https://fragment.com/number/{num}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
        content = r.text.lower()
        if "restricted" in content:
            return "❌ Restricted"
        if "anonymous number" in content:
            return "✅ OK"
        return "❔ Unknown"
    except Exception:
        return "⚠️ Error"

async def checknum_concurrent(nums: list[str]) -> list[tuple[str, str]]:
    sem = asyncio.Semaphore(50)  # up to 50 concurrent checks
    async def sem_check(n: str):
        async with sem:
            return n, await fetch_status(n)
    normalized = [normalize_num(n) for n in nums]
    return await asyncio.gather(*(sem_check(n) for n in normalized))

async def process_query(user_id: int, text: str) -> str:
    """Append to memory, build prompt, call ChatGPT, update memory."""
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": text})

    prompt = SYSTEM_PROMPT + "".join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in history
    )

    resp = await api.chatgpt(prompt)
    answer = resp.message or "I'm sorry, something went wrong."

    history.append({"role": "bot", "content": answer})
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]
    return answer

async def keep_typing(chat_id: int, stop_evt: asyncio.Event):
    """Send typing indicator until stop_evt is set."""
    while not stop_evt.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

# ─── HANDLERS ──────────────────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis—just send +888 numbers or ask any question, and I'll remember and reply."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def dm_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    # Record user message
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": text})
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]

    # Detect number tokens (split on commas or newlines)
    raw_tokens = re.split(r"[,\n]+", text)
    nums = []
    for tok in raw_tokens:
        tok = tok.strip()
        # First try: remove all spaces
        candidate = re.sub(r"\s+", "", tok)
        if re.fullmatch(r"\+?\d{11,}", candidate) and candidate.lstrip("+").startswith("888"):
            nums.append(candidate.lstrip("+"))
        else:
            # Otherwise, accumulate parts until 11+ digits
            cleaned = ""
            for part in tok.split():
                cleaned += re.sub(r"\D", "", part)
                if len(cleaned) >= 11:
                    break
            if len(cleaned) >= 11 and cleaned.startswith("888"):
                nums.append(cleaned)

    # Deduplicate, preserve order
    seen = set()
    nums = [n for n in nums if not (n in seen or seen.add(n))]

    if nums:
        count = len(nums)
        header = f"🔍 Checking *{count}* number{'s' if count>1 else ''}…"
        status = await message.reply(header, parse_mode=ParseMode.MARKDOWN)

        stop_evt = asyncio.Event()
        typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
        try:
            results = await checknum_concurrent(nums)
            asc = sorted(results, key=lambda x: int(x[0]))
            desc = list(reversed(asc))

            asc_lines = ["🔢 *Ascending Order:*"] + [f"{n}: {s}" for n, s in asc]
            desc_lines = ["🔢 *Descending Order:*"] + [f"{n}: {s}" for n, s in desc]
            full_reply = "\n".join(asc_lines + [""] + desc_lines)

            await message.reply(full_reply)
            history.append({"role": "bot", "content": full_reply})
            if len(history) > MAX_HISTORY:
                del history[:-MAX_HISTORY]

            await status.delete()
        finally:
            stop_evt.set()
            await typer
        return

    # Free-form ChatGPT fallback
    status = await message.reply("🧠 Thinking…")
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
    try:
        answer = await process_query(user_id, text)
        await status.edit_text(html.escape(answer), parse_mode=None)
    finally:
        stop_evt.set()
        await typer

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis is starting with memory & on-demand checks…")
    dp.run_polling(bot)


