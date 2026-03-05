import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from store import DataStore
from config import MAX_WALLETS

logger = logging.getLogger(__name__)
store  = DataStore()

WAITING_FOR_ADDRESS = 1
WAITING_FOR_NAME    = 2

def cid(u): return u.effective_chat.id

# ── KEYBOARDS ─────────────────────────────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Wallet",     callback_data="menu_add"),
         InlineKeyboardButton("🗑 Remove Wallet",  callback_data="menu_remove")],
        [InlineKeyboardButton("📋 My Wallets",     callback_data="menu_list"),
         InlineKeyboardButton("📡 Status",         callback_data="menu_status")],
        [InlineKeyboardButton("🎯 Set Threshold",  callback_data="menu_threshold"),
         InlineKeyboardButton("🍃 Eco Mode",       callback_data="menu_ecomode")],
        [InlineKeyboardButton("📈 Credits",        callback_data="menu_credits")],
    ])

def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("‹ Main Menu", callback_data="menu_main")]
    ])

def wallets_kb(wallets: dict):
    buttons = []
    for i, (addr, info) in enumerate(wallets.items()):
        name = info.get("name", "Unnamed")
        buttons.append([
            InlineKeyboardButton(f"✅ {name}", callback_data=f"noop"),
            InlineKeyboardButton("✕", callback_data=f"rm_{addr}")
        ])
    buttons.append([InlineKeyboardButton("‹ Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)

# ── START ─────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type  = update.effective_chat.type
    wallet_cnt = store.get_wallet_count(cid(update))
    threshold  = store.get_threshold(cid(update))
    eco        = store.get_eco_mode(cid(update))

    scope = "👤 Private" if chat_type == "private" else "👥 Group"
    ready = wallet_cnt >= 2

    text = (
        f"👁  *WALLET TRACKER*\n"
        f"\n"
        f"Multi-wallet buy signal detector for Solana.\n"
        f"Get alerted when {threshold}+ tracked wallets buy the same token.\n"
        f"\n"
        f"{'⚡  Full Mode' if not eco else '🍃  Eco Mode'}   ·   "
        f"{scope}   ·   "
        f"{'🟢 Active' if ready else '🔴 Need wallets'}\n"
        f"·  *{wallet_cnt}* wallets tracked   ·   threshold *{threshold}*"
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ── CALLBACK ROUTER ───────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    if data == "menu_main":
        await start(update, context)

    elif data == "menu_add":
        await q.edit_message_text(
            "➕  *ADD WALLET*\n\nPaste the Solana wallet address:",
            parse_mode="Markdown", reply_markup=back_kb()
        )
        context.user_data["waiting"] = "add_address"

    elif data == "menu_remove":
        wallets = store.get_wallets(cid(update))
        if not wallets:
            await q.edit_message_text(
                "📭  No wallets to remove.",
                reply_markup=back_kb()
            )
        else:
            await q.edit_message_text(
                f"🗑  *REMOVE WALLET*\n\nTap ✕ next to the wallet to remove:",
                parse_mode="Markdown", reply_markup=wallets_kb(wallets)
            )

    elif data.startswith("rm_"):
        address = data[3:]
        wallets = store.get_wallets(cid(update))
        name    = wallets.get(address, {}).get("name", address[:8] + "...")
        store.remove_wallet(cid(update), address)
        remaining = store.get_wallets(cid(update))
        if remaining:
            await q.edit_message_text(
                f"✅  *{name}* removed.\n\nTap ✕ to remove another:",
                parse_mode="Markdown", reply_markup=wallets_kb(remaining)
            )
        else:
            await q.edit_message_text(
                f"✅  *{name}* removed.\n\nNo more wallets.",
                parse_mode="Markdown", reply_markup=back_kb()
            )

    elif data == "menu_list":
        await show_wallets(update, context)

    elif data == "menu_status":
        await show_status(update, context)

    elif data == "menu_threshold":
        threshold = store.get_threshold(cid(update))
        await q.edit_message_text(
            f"🎯  *SET THRESHOLD*\n\n"
            f"Current threshold: *{threshold}* wallets\n\n"
            f"This is how many tracked wallets must buy the same\n"
            f"token within 10 minutes to trigger an alert.\n\n"
            f"Type a number to change it:",
            parse_mode="Markdown", reply_markup=back_kb()
        )
        context.user_data["waiting"] = "threshold"

    elif data == "menu_ecomode":
        await toggle_ecomode(update, context)

    elif data == "menu_credits":
        await show_credits(update, context)

    elif data == "noop":
        pass  # wallet name button — no action

# ── MESSAGE ROUTER ────────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting = context.user_data.get("waiting")
    if not waiting:
        await update.message.reply_text("Use the menu 👇", reply_markup=main_menu_kb())
        return

    text = update.message.text.strip()

    if waiting == "add_address":
        if len(text) < 32 or len(text) > 44 or " " in text:
            await update.message.reply_text(
                "❌  Invalid address — must be 32-44 chars.\nTry again:",
                reply_markup=back_kb()
            )
            return
        if store.wallet_exists(cid(update), text):
            name = store.get_wallets(cid(update)).get(text, {}).get("name", "?")
            await update.message.reply_text(
                f"⚠️  Already tracking this wallet as *{name}*.\nSend a different address:",
                parse_mode="Markdown", reply_markup=back_kb()
            )
            return
        if store.get_wallet_count(cid(update)) >= MAX_WALLETS:
            await update.message.reply_text(
                f"❌  Wallet limit ({MAX_WALLETS}) reached.",
                reply_markup=main_menu_kb()
            )
            context.user_data.clear()
            return
        context.user_data["pending_address"] = text
        context.user_data["waiting"] = "add_name"
        await update.message.reply_text(
            f"✅  *Address saved*\n`{text}`\n\nNow give it a name:\n_e.g. Whale1, Alpha KOL, Bruski_",
            parse_mode="Markdown", reply_markup=back_kb()
        )

    elif waiting == "add_name":
        if len(text) > 30:
            await update.message.reply_text("❌  Name too long (max 30 chars). Try again:")
            return
        address = context.user_data.get("pending_address")
        if not address:
            await update.message.reply_text("❌  Session expired. Start over.", reply_markup=main_menu_kb())
            context.user_data.clear()
            return
        store.add_wallet(cid(update), address, text)
        count = store.get_wallet_count(cid(update))
        context.user_data.clear()
        await update.message.reply_text(
            f"✅  *{text}* added!\n`{address}`\n\n·  Total wallets: *{count}*",
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )

    elif waiting == "threshold":
        try:
            val = int(text)
            if val < 2:
                await update.message.reply_text("❌  Minimum is 2. Try again:")
                return
            count = store.get_wallet_count(cid(update))
            if val > count:
                await update.message.reply_text(
                    f"⚠️  You only have {count} wallets — threshold can't exceed that. Try again:"
                )
                return
            store.set_threshold(cid(update), val)
            context.user_data.clear()
            await update.message.reply_text(
                f"✅  Threshold set to *{val}* wallets.",
                parse_mode="Markdown", reply_markup=main_menu_kb()
            )
        except ValueError:
            await update.message.reply_text("❌  Enter a number. Try again:")

# ── MENU SCREENS ──────────────────────────────────────────────────────────────

async def show_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    wallets = store.get_wallets(cid(update))
    if not wallets:
        await q.edit_message_text(
            "📭  *MY WALLETS*\n\nNo wallets tracked yet.\nTap ➕ Add Wallet to get started.",
            parse_mode="Markdown", reply_markup=back_kb()
        )
        return
    count = len(wallets)
    lines = [f"📋  *MY WALLETS  ·  {count} tracked*\n"]
    for i, (addr, info) in enumerate(wallets.items(), 1):
        name = info.get("name", "Unnamed")
        lines.append(f"*{i}.*  {name}\n     `{addr[:20]}...`")
    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown", reply_markup=back_kb()
    )

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q          = update.callback_query
    chat_type  = update.effective_chat.type
    wallet_cnt = store.get_wallet_count(cid(update))
    threshold  = store.get_threshold(cid(update))
    eco        = store.get_eco_mode(cid(update))
    tracker    = q.bot_data.get("tracker") if hasattr(q, "bot_data") else None
    running    = True  # tracker is always running if bot is up

    scope = "👤 Private DM" if chat_type == "private" else "👥 Group"
    ready = wallet_cnt >= 2

    text = (
        f"📡  *TRACKER STATUS*\n\n"
        f"·  Context       {scope}\n"
        f"·  Running       {'🟢 Yes' if running else '🔴 No'}\n"
        f"·  Wallets       *{wallet_cnt}*\n"
        f"·  Threshold     *{threshold}* wallets\n"
        f"·  Mode          {'🍃 Eco' if eco else '⚡ Full'}\n"
        f"·  Poll rate     {'60s' if eco else '10s'}\n"
        f"·  Ready         {'✅ Alerts active' if ready else '❌ Add more wallets'}"
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())

async def toggle_ecomode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    new = not store.get_eco_mode(cid(update))
    store.set_eco_mode(cid(update), new)
    if new:
        text = (
            "🍃  *ECO MODE  ON*\n\n"
            "Credit usage reduced ~80%.\n\n"
            "·  Poll rate     *60s*\n"
            "·  Txns fetched  *5 per wallet*\n\n"
            "_Alerts may be up to 60s slower. Best when not actively trading._"
        )
    else:
        text = (
            "⚡  *FULL MODE  ON*\n\n"
            "Maximum speed restored.\n\n"
            "·  Poll rate     *10s*\n"
            "·  Txns fetched  *10 per wallet*"
        )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())

async def show_credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q          = update.callback_query
    used       = store.get_credits_used()
    limit      = 100_000
    rem        = max(0, limit - used)
    pct        = round((used / limit) * 100, 1)
    eco        = store.get_eco_mode(cid(update))
    wallet_cnt = store.get_wallet_count(cid(update))
    filled     = round(pct / 10)
    bar        = "▰" * filled + "▱" * (10 - filled)
    daily_est  = wallet_cnt * (1440 if eco else 8640)
    days_left  = round(rem / daily_est) if daily_est > 0 else 999
    text = (
        f"📈  *HELIUS CREDITS*\n\n"
        f"{bar}  {pct}%\n\n"
        f"·  Used         *{used:,}*\n"
        f"·  Remaining    *{rem:,}*\n"
        f"·  Monthly cap  *{limit:,}*\n"
        f"·  Est. days    *~{days_left}d*\n\n"
        f"{'🍃  Eco mode ON' if eco else '⚡  Full mode ON'}\n\n"
        f"_/resetcredits to reset on month start_"
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())

# ── LEGACY COMMANDS (still work if typed) ────────────────────────────────────

async def add_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting"] = "add_address"
    await update.message.reply_text(
        "➕  *ADD WALLET*\n\nPaste the Solana wallet address:",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    return WAITING_FOR_ADDRESS

async def add_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await message_handler(update, context)
    if context.user_data.get("waiting") == "add_name":
        return WAITING_FOR_NAME
    return ConversationHandler.END

async def add_wallet_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await message_handler(update, context)
    return ConversationHandler.END

async def add_wallet_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌  Usage: `/removewallet <address>`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    wallets = store.get_wallets(cid(update))
    name    = wallets.get(address, {}).get("name", address[:8] + "...")
    if store.remove_wallet(cid(update), address):
        await update.message.reply_text(f"✅  *{name}* removed.", parse_mode="Markdown", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("❌  Wallet not found.", reply_markup=main_menu_kb())

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = store.get_wallets(cid(update))
    if not wallets:
        await update.message.reply_text("📭  No wallets tracked yet.", reply_markup=main_menu_kb())
        return
    lines = [f"📋  *MY WALLETS  ·  {len(wallets)} tracked*\n"]
    for i, (addr, info) in enumerate(wallets.items(), 1):
        lines.append(f"*{i}.*  {info.get('name','Unnamed')}\n     `{addr}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_kb())

async def set_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        t = store.get_threshold(cid(update))
        await update.message.reply_text(f"🎯  Threshold: *{t}* wallets\n\n`/threshold <number>` to change.", parse_mode="Markdown")
        return
    try:
        val = int(context.args[0])
        store.set_threshold(cid(update), val)
        await update.message.reply_text(f"✅  Threshold → *{val}*", parse_mode="Markdown", reply_markup=main_menu_kb())
    except ValueError:
        await update.message.reply_text("❌  Enter a number.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    eco        = store.get_eco_mode(cid(update))
    wallet_cnt = store.get_wallet_count(cid(update))
    threshold  = store.get_threshold(cid(update))
    await update.message.reply_text(
        f"📡  *STATUS*\n\n"
        f"·  Wallets    *{wallet_cnt}*\n"
        f"·  Threshold  *{threshold}*\n"
        f"·  Mode       {'🍃 Eco' if eco else '⚡ Full'}",
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )

async def ecomode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = not store.get_eco_mode(cid(update))
    store.set_eco_mode(cid(update), new)
    await update.message.reply_text(
        f"{'🍃 Eco Mode ON' if new else '⚡ Full Mode ON'}",
        reply_markup=main_menu_kb()
    )

async def credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    used  = store.get_credits_used()
    limit = 100_000
    rem   = max(0, limit - used)
    pct   = round((used / limit) * 100, 1)
    await update.message.reply_text(
        f"📈  *CREDITS*\n\n·  Used {used:,}  ·  Remaining {rem:,}  ·  {pct}%",
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )

async def resetcredits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store.reset_credits()
    await update.message.reply_text("🔄  Credits reset.", reply_markup=main_menu_kb())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await message_handler(update, context)
