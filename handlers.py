import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from store import DataStore
from config import MAX_WALLETS

logger = logging.getLogger(__name__)
store = DataStore()

WAITING_FOR_ADDRESS = 1
WAITING_FOR_NAME = 2

def get_chat_id(update: Update) -> int:
    return update.effective_chat.id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)
    chat_type = update.effective_chat.type

    if chat_type == "private":
        context_label = "your personal DMs"
    else:
        context_label = f"this group"

    msg = (
        f"👁 *Solana Multi-Wallet Buy Tracker*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Wallets added here are *only visible to {context_label}*.\n"
        f"Each chat has its own completely separate wallet list.\n\n"
        f"Tap / to see all commands.\n\n"
        f"Add at least *70 wallets* to start tracking."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── ADD WALLET — Conversational flow ────────────

async def add_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👛 *Add a Wallet — Step 1 of 2*\n\n"
        "Send me the *Solana wallet address* you want to track:",
        parse_mode="Markdown"
    )
    return WAITING_FOR_ADDRESS

async def add_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)
    address = update.message.text.strip()

    if len(address) < 32 or len(address) > 44:
        await update.message.reply_text(
            "❌ That doesn't look like a valid Solana address (32-44 characters).\n\n"
            "Try again or type /cancel."
        )
        return WAITING_FOR_ADDRESS

    if store.wallet_exists(chat_id, address):
        existing = store.get_wallets(chat_id).get(address, {})
        name = existing.get("name", "Unknown")
        await update.message.reply_text(
            f"⚠️ Already tracking this wallet as *{name}* in this chat.\n\n"
            "Send a different address or type /cancel.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_ADDRESS

    if store.get_wallet_count(chat_id) >= MAX_WALLETS:
        await update.message.reply_text(f"❌ Maximum wallet limit ({MAX_WALLETS}) reached for this chat.")
        return ConversationHandler.END

    context.user_data["pending_address"] = address

    await update.message.reply_text(
        f"✅ *Address received!*\n`{address}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Step 2 of 2* — Give this wallet a name:\n\n"
        f"Examples: _Whale1_, _Alpha Caller_, _KOL 5_",
        parse_mode="Markdown"
    )
    return WAITING_FOR_NAME

async def add_wallet_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)
    name = update.message.text.strip()
    address = context.user_data.get("pending_address")

    if not address:
        await update.message.reply_text("❌ Something went wrong. Type /addwallet and try again.")
        return ConversationHandler.END

    if len(name) > 30:
        await update.message.reply_text("❌ Name too long. Keep it under 30 characters:")
        return WAITING_FOR_NAME

    store.add_wallet(chat_id, address, name)
    new_count = store.get_wallet_count(chat_id)
    context.user_data.clear()

    msg = (
        f"🎉 *Wallet added!*\n\n"
        f"👛 Name: *{name}*\n"
        f"📋 Address: `{address}`\n\n"
        f"📊 Wallets in this chat: *{new_count}*"
    )
    if new_count < 70:
        msg += f"\n⚠️ Need *{70 - new_count}* more to reach minimum (70)."
    else:
        msg += f"\n✅ Tracking {new_count} wallets — alerts active!"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

async def add_wallet_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ── OTHER COMMANDS ───────────────────────────────

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)

    if not context.args:
        await update.message.reply_text(
            "❌ Usage: `/removewallet <address>`",
            parse_mode="Markdown"
        )
        return

    address = context.args[0].strip()
    wallets = store.get_wallets(chat_id)
    name = wallets.get(address, {}).get("name", address[:8] + "...")

    if store.remove_wallet(chat_id, address):
        await update.message.reply_text(
            f"🗑 Removed *{name}*\n"
            f"📊 Wallets in this chat: *{store.get_wallet_count(chat_id)}*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Wallet not found in this chat.")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)
    wallets = store.get_wallets(chat_id)

    if not wallets:
        await update.message.reply_text(
            "📭 No wallets tracked in this chat yet.\n"
            "Use /addwallet to add one."
        )
        return

    count = len(wallets)
    lines = [f"👛 *Wallets in this chat ({count}):*\n"]
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
    chat_id = get_chat_id(update)

    if not context.args:
        current = store.get_threshold(chat_id)
        await update.message.reply_text(
            f"📊 Current threshold: *{current}* wallets\n"
            "Use `/threshold <number>` to change.\n"
            "Example: `/threshold 3`",
            parse_mode="Markdown"
        )
        return

    try:
        value = int(context.args[0])
        if value < 2:
            await update.message.reply_text("❌ Threshold must be at least 2.")
            return
        count = store.get_wallet_count(chat_id)
        if value > count:
            await update.message.reply_text(
                f"⚠️ Threshold ({value}) is higher than your wallet count ({count}).\n"
                "You'd never get alerts. Use a lower number."
            )
            return
        store.set_threshold(chat_id, value)
        await update.message.reply_text(
            f"✅ Threshold set to *{value}* wallets for this chat.",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number. Example: `/threshold 3`", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = get_chat_id(update)
    chat_type = update.effective_chat.type
    tracker = context.bot_data.get('tracker')

    wallet_count = store.get_wallet_count(chat_id)
    threshold = store.get_threshold(chat_id)
    is_running = tracker.running if tracker else False
    is_ready = wallet_count >= 70

    chat_label = "DM (private)" if chat_type == "private" else "Group chat"

    msg = (
        f"📡 *Tracker Status*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Context: *{chat_label}*\n"
        f"🔄 Running: {'✅ Yes' if is_running else '❌ No'}\n"
        f"👛 Wallets in this chat: *{wallet_count}*\n"
        f"🎯 Alert threshold: *{threshold}* wallets\n"
        f"✅ Ready: {'Yes' if is_ready else f'No — need {70 - wallet_count} more'}\n\n"
        f"_Wallets here are only visible to this chat._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👁 *Solana Multi-Wallet Buy Tracker*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Commands:*\n"
        "/addwallet — Add a wallet to this chat\n"
        "/removewallet — Remove a wallet from this chat\n"
        "/wallets — List wallets tracked in this chat\n"
        "/threshold — Set alert threshold for this chat\n"
        "/status — Show status for this chat\n"
        "/help — This message\n\n"
        "🔒 Each chat has its own private wallet list.\n"
        "Wallets added here never appear in other chats."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Tap / to see all commands.")
