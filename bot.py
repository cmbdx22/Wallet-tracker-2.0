import asyncio
import logging
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ConversationHandler
)
from config import TELEGRAM_BOT_TOKEN
from handlers import (
    start, add_wallet_start, add_wallet_address, add_wallet_name,
    add_wallet_cancel, remove_wallet, list_wallets,
    set_threshold, status, help_command, handle_text,
    WAITING_FOR_ADDRESS, WAITING_FOR_NAME
)
from tracker import WalletTracker

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def set_bot_commands(app):
    """Register the slash command menu shown when user taps /"""
    commands = [
        BotCommand("addwallet",    "Add a wallet to track"),
        BotCommand("removewallet", "Remove a tracked wallet"),
        BotCommand("wallets",      "List all tracked wallets"),
        BotCommand("threshold",    "Set alert threshold"),
        BotCommand("status",       "Show tracker status"),
        BotCommand("help",         "Show help menu"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands menu registered.")

async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    tracker = WalletTracker(app)
    app.bot_data['tracker'] = tracker

    # Conversational handler for /addwallet
    add_wallet_conv = ConversationHandler(
        entry_points=[CommandHandler("addwallet", add_wallet_start)],
        states={
            WAITING_FOR_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_wallet_address)
            ],
            WAITING_FOR_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_wallet_name)
            ],
        },
        fallbacks=[CommandHandler("cancel", add_wallet_cancel)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_wallet_conv)
    app.add_handler(CommandHandler("removewallet", remove_wallet))
    app.add_handler(CommandHandler("wallets", list_wallets))
    app.add_handler(CommandHandler("threshold", set_threshold))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await app.initialize()
    await set_bot_commands(app)
    await app.start()

    asyncio.create_task(tracker.start_tracking())

    logger.info("Bot started. Beginning polling...")
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    finally:
        await tracker.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
