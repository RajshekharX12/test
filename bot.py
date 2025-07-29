import os
import re
import logging
import asyncio
import httpx

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.enums.chat_action import ChatAction
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from SafoneAPI.errors import GenericApiError
from dotenv import load_dotenv

# ─── CONFIG ────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY ────────────────────────────────────────────────────
conversation_histories: dict[int, list[dict[str,str]]] = {}
MAX_HISTORY = 20
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
    url = f"https://fragment.com/number/{num}/code"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        data = await resp.json()
        st = data.get("status", "").lower()
        if "restricted" in st:
            return "❌ Restricted"
        if "anonymous" in st or "free" in st:
            return "✅ OK"
        return "❔ Unknown"
    except Exception:
        return "⚠️ Error"

async def checknum_concurrent(nums: list[str]) -> list[tuple[str,str]]:
    sem = asyncio.Semaphore(50)
    async def sem_check(n: str):
        async with sem:
            return n, await fetch_status(n)
    normalized = [normalize_num(n) for n in nums]
    return await asyncio.gather(*(sem_check(n) for n in normalized))

async def process_query(user_id: int, text: str) -> str:
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role":"user","content":text})
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]

    def build_prompt():
        return SYSTEM_PROMPT + "".join(
            f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
            for m in history
        )

    prompt = build_prompt()
    try:
        resp = await api.chatgpt(prompt)
    except GenericApiError as e:
        if "reduce the context" in str(e).lower():
            last = history[-1]
            history.clear()
            history.append(last)
            prompt = build_prompt()
            resp = await api.chatgpt(prompt)
        else:
            raise

    answer = resp.message or "I'm sorry, something went wrong."
    history.append({"role":"bot","content":answer})
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]
    return answer

async def get_status_message() -> str:
    prompt = (
        "You are Jarvis, a witty AI assistant. "
        "In one playful sentence, describe what you’re up to right now."
    )
    resp = await api.chatgpt(prompt)
    return (resp.message or "Jarvis is working...").strip().strip('"')

async def keep_typing(chat_id: int, stop_evt: asyncio.Event):
    while not stop_evt.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

# ─── HANDLERS ──────────────────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I'm Jarvis—send +888 numbers to check which ones are restricted."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def dm_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    # record user
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role":"user","content":text})
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]

    # detect numbers
    raw = re.split(r"[,\n]+", text)
    nums = []
    for tok in raw:
        tok = tok.strip()
        cand = re.sub(r"\s+", "", tok)
        if re.fullmatch(r"\+?\d{11,}", cand) and cand.lstrip("+").startswith("888"):
            nums.append(cand.lstrip("+"))
        else:
            cleaned = ""
            for p in tok.split():
                cleaned += re.sub(r"\D", "", p)
                if len(cleaned) >= 11:
                    break
            if len(cleaned) >= 11 and cleaned.startswith("888"):
                nums.append(cleaned)
    seen = set()
    nums = [n for n in nums if not (n in seen or seen.add(n))]

    if nums:
        status_text = await get_status_message()
        status = await message.reply(status_text)
        stop_evt = asyncio.Event()
        typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
        try:
            results = await checknum_concurrent(nums)
            restricted = [n for n,s in results if s=="❌ Restricted"]
            if restricted:
                reply = "🔴 Restricted numbers:\n" + "\n".join(restricted)
            else:
                reply = "✅ No restricted numbers found."

            # send in chunks if needed
            lines = reply.split("\n")
            for i in range(0, len(lines), 40):
                await message.reply("\n".join(lines[i:i+40]), parse_mode=ParseMode.MARKDOWN)

            history.append({"role":"bot","content":reply})
            if len(history) > MAX_HISTORY:
                del history[:-MAX_HISTORY]

            await status.delete()
        finally:
            stop_evt.set()
            await typer
        return

    # fallback to chatgpt
    status_text = await get_status_message()
    status = await message.reply(status_text)
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
    try:
        answer = await process_query(user_id, text)
        await status.edit_text(answer, parse_mode=None)
        history.append({"role":"bot","content":answer})
        if len(history) > MAX_HISTORY:
            del history[:-MAX_HISTORY]
    finally:
        stop_evt.set()
        await typer

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    dp.run_polling(bot)
