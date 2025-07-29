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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY ────────────────────────────────────────────────────
# conversation_histories[user_id] = [ {"role":"user"|"bot","content":str}, ... ]
conversation_histories: dict[int, list[dict[str,str]]] = {}
MAX_HISTORY = 20  # total messages (user+bot) to remember per user

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly Hindi or English with emojis.\n\n"
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
            r = await client.get(url)
        txt = r.text.lower()
        if "restricted on telegram" in txt:
            return "❌ Restricted"
        if "anonymous number" in txt or "free" in txt:
            return "✅ OK"
        return "❔ Unknown"
    except Exception:
        return "⚠️ Error"

async def checknum_concurrent(nums: list[str]) -> list[tuple[str,str]]:
    sem = asyncio.Semaphore(50)  # up to 50 parallel requests
    async def sem_check(n: str):
        async with sem:
            return n, await fetch_status(n)
    normalized = [normalize_num(n) for n in nums]
    return await asyncio.gather(*(sem_check(n) for n in normalized))

async def process_query(user_id: int, text: str) -> str:
    """Append to memory, build prompt from memory + text, call ChatGPT, update memory."""
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role":"user","content":text})

    # build prompt
    prompt = SYSTEM_PROMPT + "\n".join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}"
        for m in history
    )

    resp = await api.chatgpt(prompt)
    answer = resp.message or "Maaf kijiye, Master—kuch galat ho gaya."

    history.append({"role":"bot","content":answer})
    # trim oldest if too long
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
    welcome = (
        "👋 नमस्ते, Master! मैं Jarvis हूँ—बस +888 नंबर भेजें "
        "या कोई भी सवाल टाइप करें, मैं याद रखूँगा और जवाब दूँगा।"
    )
    await message.answer(welcome)

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def dm_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    # Record the user's message in memory
    conversation_histories.setdefault(user_id, []).append({"role":"user","content":text})
    # Trim
    if len(conversation_histories[user_id]) > MAX_HISTORY:
        del conversation_histories[user_id][:-MAX_HISTORY]

    # Number-check branch
    tokens = re.split(r"[,\s]+", text)
    nums = [t for t in tokens if re.fullmatch(r"\+?\d+", t)]
    if nums:
        count = len(nums)
        header = f"🔍 Checking *{count}* number{'s' if count>1 else ''}…"
        status = await message.reply(header)

        stop_evt = asyncio.Event()
        typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
        try:
            results = await checknum_concurrent(nums)
            asc = sorted(results, key=lambda x: int(x[0]))
            desc = list(reversed(asc))

            # Build response text
            asc_lines = ["🔢 *Ascending Order:*"] + [f"{n}: {s}" for n,s in asc]
            desc_lines = ["🔢 *Descending Order:*"] + [f"{n}: {s}" for n,s in desc]
            full_reply = "\n".join(asc_lines + [""] + desc_lines)

            # Send reply
            await message.reply(full_reply)

            # Record Jarvis’s reply in memory
            conversation_histories[user_id].append({"role":"bot","content":full_reply})
            if len(conversation_histories[user_id]) > MAX_HISTORY:
                del conversation_histories[user_id][:-MAX_HISTORY]

            # clean up header
            await status.delete()
        finally:
            stop_evt.set()
            await typer
        return

    # Free-form ChatGPT branch
    status = await message.reply("🧠 सोच रहा हूँ…")
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))
    try:
        answer = await process_query(user_id, text)
        # Update the last bot entry in memory (already done in process_query)
        await status.edit_text(html.escape(answer), parse_mode=None)
    finally:
        stop_evt.set()
        await typer

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis is starting with memory & on-demand checks…")
    dp.run_polling(bot)

