import logging
from telegram import Update
from telegram.ext import ContextTypes
from store import DataStore
from config import MAX_WALLETS

logger = logging.getLogger(__name__)
store = DataStore()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.add_chat_id(chat_id)
    msg = (
        "👁 *Solana Multi-Wallet Buy Tracker*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Track 70+ wallets and get alerted when multiple wallets buy the same token.\n\n"
        "*Commands:*\n"
        "/addwallet `<address> <name>` — Add a wallet\n"
        "/removewallet `<address>` — Remove a wallet\n"
        "/wallets — List all tracked wallets\n"
        "/threshold `<number>` — Set min wallets to trigger alert (default: 2)\n"
        "/status — Show tracker status\n"
        "/help — Show this message\n\n"
        "Add at least *70 wallets* to start tracking."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.add_chat_id(chat_id)

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/addwallet <address> <name>`\n"
            "Example: `/addwallet 7xKX...abc3 Whale1`",
            parse_mode="Markdown"
        )
        return

    address = context.args[0].strip()
    name = " ".join(context.args[1:]).strip()

    # Basic Solana address validation
    if len(address) < 32 or len(address) > 44:
        await update.message.reply_text("❌ Invalid Solana address. Must be 32-44 characters.")
        return

    current_count = store.get_wallet_count()
    if current_count >= MAX_WALLETS:
        await update.message.reply_text(f"❌ Maximum wallet limit ({MAX_WALLETS}) reached.")
        return

    wallets = store.get_wallets()
    if address in wallets:
        await update.message.reply_text(f"⚠️ Wallet already tracked as *{wallets[address]['name']}*", parse_mode="Markdown")
        return

    store.add_wallet(address, name, chat_id)
    new_count = store.get_wallet_count()
    
    msg = f"✅ Added wallet *{name}*\n`{address}`\n\n📊 Total wallets: *{new_count}*"
    if new_count < 70:
        msg += f"\n⚠️ Need {70 - new_count} more wallets to reach minimum (70)."
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/removewallet <address>`", parse_mode="Markdown")
        return

    address = context.args[0].strip()
    wallets = store.get_wallets()
    wallet_info = wallets.get(address, {})
    name = wallet_info.get("name", address[:8] + "...")

    if store.remove_wallet(address):
        await update.message.reply_text(
            f"🗑 Removed wallet *{name}*\n📊 Total wallets: *{store.get_wallet_count()}*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Wallet not found.")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = store.get_wallets()
    if not wallets:
        await update.message.reply_text("📭 No wallets tracked yet. Use /addwallet to add some.")
        return

    count = len(wallets)
    lines = [f"👛 *Tracked Wallets ({count}):*\n"]
    
    for i, (addr, info) in enumerate(wallets.items(), 1):
        name = info.get("name", "Unnamed")
        lines.append(f"{i}. *{name}*\n   `{addr}`")

    # Split into chunks if too long
    full_msg = "\n".join(lines)
    if len(full_msg) > 4000:
        chunks = []
        chunk = lines[0]
        for line in lines[1:]:
            if len(chunk) + len(line) > 3800:
                chunks.append(chunk)
                chunk = line
            else:
                chunk += "\n" + line
        chunks.append(chunk)
        for c in chunks:
            await update.message.reply_text(c, parse_mode="Markdown")
    else:
        await update.message.reply_text(full_msg, parse_mode="Markdown")

async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = store.get_threshold()
        await update.message.reply_text(
            f"📊 Current threshold: *{current}* wallets\n"
            "Use `/threshold <number>` to change it.",
            parse_mode="Markdown"
        )
        return

    try:
        value = int(context.args[0])
        if value < 2:
            await update.message.reply_text("❌ Threshold must be at least 2.")
            return
        if value > store.get_wallet_count():
            await update.message.reply_text(
                f"⚠️ Threshold ({value}) is higher than your wallet count ({store.get_wallet_count()}). "
                "You'll never get alerts. Set a lower value."
            )
            return
        store.set_threshold(value)
        await update.message.reply_text(f"✅ Alert threshold set to *{value}* wallets.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tracker = context.bot_data.get('tracker')
    wallet_count = store.get_wallet_count()
    threshold = store.get_threshold()
    is_running = tracker.running if tracker else False
    is_ready = wallet_count >= 70

    msg = (
        f"📡 *Tracker Status*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 Running: {'✅ Yes' if is_running else '❌ No'}\n"
        f"👛 Wallets tracked: *{wallet_count}*\n"
        f"🎯 Alert threshold: *{threshold}* wallets\n"
        f"📊 Min required: *70 wallets*\n"
        f"✅ Ready: {'Yes' if is_ready else f'No — need {70 - wallet_count} more'}\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Use /help to see available commands."
    )
