import asyncio
import logging
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from config import TELEGRAM_BOT_TOKEN
from handlers import (
    start, help_command, button_handler, message_handler,
    remove_wallet, list_wallets, set_threshold, status,
    ecomode_command, credits_command, resetcredits_command,
    WAITING_FOR_ADDRESS, WAITING_FOR_NAME
)
from tracker import WalletTracker

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

tracker: WalletTracker = None

async def post_init(app: Application):
    """
    Called by PTB after the app is fully initialised and the event loop
    is running. This is the correct place to launch background tasks.
    asyncio.create_task() in main() fires before the loop is ready
    which silently swallows the task on some Python/PTB versions.
    """
    global tracker
    logger.info("post_init: launching tracker background task...")
    app.create_task(tracker.start_tracking())
    logger.info("post_init: tracker task created.")

    await app.bot.set_my_commands([
        BotCommand("start",        "Open main menu"),
        BotCommand("threshold",    "Set alert threshold"),
        BotCommand("resetcredits", "Reset monthly credit counter"),
        BotCommand("cancel",       "Cancel current action"),
    ])

def main():
    global tracker

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)   # <-- runs AFTER loop is ready
        .build()
    )

    tracker = WalletTracker(app)
    app.bot_data["tracker"] = tracker

    # Inline buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Commands
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("help",         help_command))
    app.add_handler(CommandHandler("removewallet", remove_wallet))
    app.add_handler(CommandHandler("wallets",      list_wallets))
    app.add_handler(CommandHandler("threshold",    set_threshold))
    app.add_handler(CommandHandler("status",       status))
    app.add_handler(CommandHandler("ecomode",      ecomode_command))
    app.add_handler(CommandHandler("credits",      credits_command))
    app.add_handler(CommandHandler("resetcredits", resetcredits_command))

    # Plain text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Starting Wallet Tracker Bot...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
