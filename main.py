import asyncio
import logging
import sys
import os
from src.credentials import get_credentials
from src.telegram_scraper import TelegramScraper
from config import Config

# Fix Windows console encoding for Ukrainian text
if sys.platform.startswith('win'):
    os.system('chcp 65001 > nul')


# Configure logging with UTF-8 encoding
class UTF8StreamHandler(logging.StreamHandler):
    def __init__(self):
        super().__init__(sys.stdout)

    def emit(self, record):
        try:
            msg = self.format(record)
            # Safely encode for Windows console
            if sys.platform.startswith('win'):
                msg = msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(msg)
        except Exception:
            self.handleError(record)


def setup_logging():
    """Setup logging with configuration from Config class"""
    logging.basicConfig(
        level=Config.get_logging_level(),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
            UTF8StreamHandler()
        ]
    )


async def main():
    """Main function"""
    # Setup logging first
    setup_logging()
    logger = logging.getLogger(__name__)

    # Print current configuration
    Config.print_current_config()

    # Load credentials
    credentials = get_credentials()
    if not credentials:
        print("❌ Failed to load credentials. Exiting.")
        return

    # Extract credentials
    api_id = credentials['api_id']
    api_hash = credentials['api_hash']
    phone_number = credentials['phone_number']
    openai_api_key = credentials['openai_api_key']

    # Log start without exposing credentials
    logger.info("🚀 Starting Telegram scraper...")

    if Config.USE_INCREMENTAL:
        logger.info("🔄 Using incremental processing (interrupt-safe)")
    else:
        logger.info("📦 Using batch processing (original method)")

    # Create scraper instance
    scraper = TelegramScraper(api_id, api_hash, phone_number)

    try:
        # Run scraper with OpenAI processing using config settings
        await scraper.run_scraper(
            channel_username=Config.CHANNEL_USERNAME,
            search_phrase=Config.SEARCH_PHRASE,
            output_file=Config.OUTPUT_FILE,
            openai_api_key=openai_api_key,
            message_limit=Config.MESSAGE_LIMIT,
            incremental=Config.USE_INCREMENTAL,
            openai_model=Config.OPENAI_MODEL
        )

        logger.info("✅ Scraping completed successfully!")

    except KeyboardInterrupt:
        logger.info("⏹️ Interrupted by user. Exiting gracefully...")
    except Exception as e:
        logger.error(f"❌ Error in main: {e}")


def create_example_config():
    """Create an example configuration file"""
    Config.save_example_config()


if __name__ == "__main__":
    import sys

    # Check if user wants to create example config
    if len(sys.argv) > 1 and sys.argv[1] == '--create-config':
        create_example_config()
        print("\n📋 You can now:")
        print("1. Copy config.example.json to config.json")
        print("2. Edit config.json with your settings")
        print("3. Run: python main.py")
        sys.exit(0)

    asyncio.run(main())