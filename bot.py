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
)
from tracker import WalletTracker

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def main():
    app     = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await app.initialize()

    await app.bot.set_my_commands([
        BotCommand("start",        "Open main menu"),
        BotCommand("threshold",    "Set alert threshold"),
        BotCommand("resetcredits", "Reset monthly credit counter"),
        BotCommand("cancel",       "Cancel current action"),
    ])

    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot polling started â launching tracker...")

    # PTB 20.x: use asyncio.create_task AFTER polling has started
    # At this point the event loop is fully running
    tracker_task = asyncio.ensure_future(tracker.start_tracking())

    logger.info("Tracker task launched.")

    try:
        await asyncio.Event().wait()  # run forever
    finally:
        logger.info("Shutting down...")
        tracker_task.cancel()
        await tracker.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
