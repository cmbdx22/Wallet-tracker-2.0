import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from store import DataStore
from config import MAX_WALLETS

logger = logging.getLogger(__name__)
store = DataStore()

# Conversation states
WAITING_FOR_ADDRESS = 1
WAITING_FOR_NAME = 2

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.add_chat_id(chat_id)
    msg = (
        "👁 *Solana Multi-Wallet Buy Tracker*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Track 70+ wallets and get alerted when multiple wallets buy the same token.\n\n"
        "Tap / to see all available commands.\n\n"
        "Add at least *70 wallets* to start tracking."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─────────────────────────────────────────────
# ADD WALLET — Conversational 3-step flow
# ─────────────────────────────────────────────

async def add_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1 — /addwallet tapped, ask for address."""
    store.add_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "👛 *Add a Wallet — Step 1 of 2*\n\n"
        "Send me the *Solana wallet address* you want to track:",
        parse_mode="Markdown"
    )
    return WAITING_FOR_ADDRESS

async def add_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2 — Validate address, ask for name."""
    address = update.message.text.strip()

    if len(address) < 32 or len(address) > 44:
        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana address.\n"
            "It should be 32-44 characters long.\n\n"
            "Try again or type /cancel to stop."
        )
        return WAITING_FOR_ADDRESS

    wallets = store.get_wallets()
    if address in wallets:
        existing_name = wallets[address].get("name", "Unknown")
        await update.message.reply_text(
            f"⚠️ Already tracking this wallet as *{existing_name}*.\n\n"
            "Send a different address or type /cancel.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_ADDRESS

    if store.get_wallet_count() >= MAX_WALLETS:
        await update.message.reply_text(f"❌ Maximum wallet limit ({MAX_WALLETS}) reached.")
        return ConversationHandler.END

    context.user_data["pending_address"] = address

    await update.message.reply_text(
        f"✅ *Address received!*\n`{address}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*Step 2 of 2* — Give this wallet a name so you recognise it in alerts.\n\n"
        "Examples: _Whale1_, _Alpha Caller_, _Dev Wallet_, _KOL 5_\n\n"
        "What do you want to call this wallet?",
        parse_mode="Markdown"
    )
    return WAITING_FOR_NAME

async def add_wallet_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3 — Save wallet with name."""
    name = update.message.text.strip()
    address = context.user_data.get("pending_address")
    chat_id = update.effective_chat.id

    if not address:
        await update.message.reply_text("❌ Something went wrong. Type /addwallet and try again.")
        return ConversationHandler.END

    if len(name) > 30:
        await update.message.reply_text("❌ Name too long. Keep it under 30 characters and try again:")
        return WAITING_FOR_NAME

    store.add_wallet(address, name, chat_id)
    new_count = store.get_wallet_count()
    context.user_data.clear()

    msg = (
        f"🎉 *Wallet added!*\n\n"
        f"👛 Name: *{name}*\n"
        f"📋 Address: `{address}`\n\n"
        f"📊 Total wallets tracked: *{new_count}*"
    )
    if new_count < 70:
        msg += f"\n⚠️ Need *{70 - new_count}* more wallets to reach the minimum (70)."
    else:
        msg += f"\n✅ Tracking {new_count} wallets — alerts are active!"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

async def add_wallet_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled. No wallet was added.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# OTHER COMMANDS
# ─────────────────────────────────────────────

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage: `/removewallet <address>`\n"
            "Example: `/removewallet 7xKX...abc3`",
            parse_mode="Markdown"
        )
        return

    address = context.args[0].strip()
    wallets = store.get_wallets()
    wallet_info = wallets.get(address, {})
    name = wallet_info.get("name", address[:8] + "...")

    if store.remove_wallet(address):
        await update.message.reply_text(
            f"🗑 Removed *{name}*\n📊 Total wallets: *{store.get_wallet_count()}*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Wallet not found. Check the address and try again.")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = store.get_wallets()
    if not wallets:
        await update.message.reply_text("📭 No wallets tracked yet. Use /addwallet to add one.")
        return

    count = len(wallets)
    lines = [f"👛 *Tracked Wallets ({count}):*\n"]
    for i, (addr, info) in enumerate(wallets.items(), 1):
        name = info.get("name", "Unnamed")
        lines.append(f"{i}. *{name}*\n   `{addr}`")

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
            "Use `/threshold <number>` to change it.\n"
            "Example: `/threshold 3`",
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
                f"⚠️ Threshold ({value}) is higher than your wallet count ({store.get_wallet_count()}).\n"
                "You'll never get alerts at this setting. Use a lower number."
            )
            return
        store.set_threshold(value)
        await update.message.reply_text(
            f"✅ Alert threshold set to *{value}* wallets.\n"
            f"You'll be alerted when {value}+ wallets buy the same token.",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number. Example: `/threshold 3`", parse_mode="Markdown")

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
    msg = (
        "👁 *Solana Multi-Wallet Buy Tracker*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Commands:*\n"
        "/addwallet — Add a wallet to track\n"
        "/removewallet — Remove a tracked wallet\n"
        "/wallets — List all tracked wallets\n"
        "/threshold — Set how many wallets must buy to trigger alert\n"
        "/status — Show tracker status\n"
        "/help — Show this message\n\n"
        "Tap / at any time to see the full command menu."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Tap / to see all available commands.")
