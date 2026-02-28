import asyncio
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN
from handlers import (
    start, add_wallet, remove_wallet, list_wallets, 
    set_threshold, status, help_command, handle_text
)
from tracker import WalletTracker

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    tracker = WalletTracker(app)
    app.bot_data['tracker'] = tracker

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addwallet", add_wallet))
    app.add_handler(CommandHandler("removewallet", remove_wallet))
    app.add_handler(CommandHandler("wallets", list_wallets))
    app.add_handler(CommandHandler("threshold", set_threshold))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    await app.initialize()
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
