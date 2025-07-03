import os
import json
import logging


class Config:
    """
    Configuration class for Telegram Scraper

    You can modify these settings or override them with environment variables
    or a config.json file.
    """

    # ====== TELEGRAM SETTINGS ======
    CHANNEL_USERNAME = 'kpszsu'  # Ukraine Air Force channel
    SEARCH_PHRASE = 'У ніч на'  # The phrase to search for in messages

    # ====== OPENAI SETTINGS ======
    OPENAI_MODEL = 'gpt-4o-mini'  # Options: 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'
    MAX_TOKENS = 2000  # Maximum tokens for OpenAI response
    TEMPERATURE = 0  # Temperature for OpenAI (0 = deterministic)

    # ====== PROCESSING SETTINGS ======
    USE_INCREMENTAL = True  # True = incremental (interrupt-safe), False = batch processing
    MESSAGE_LIMIT = 1000  # Number of messages to process (None = all messages)

    # ====== RATE LIMITING SETTINGS ======
    REQUEST_DELAY = 1.0  # Seconds between OpenAI requests (to avoid rate limits)
    MAX_CONCURRENT_REQUESTS = 5  # Max concurrent requests for batch processing
    RETRY_MAX_TRIES = 3  # Max retries for failed OpenAI requests
    RETRY_MAX_TIME = 60  # Max time (seconds) for retry attempts

    # ====== OUTPUT SETTINGS ======
    OUTPUT_FILE = 'ukraine_airforce_updates.csv'  # Output CSV filename
    LOG_FILE = 'telegram_scraper.log'  # Log filename
    LOG_LEVEL = 'INFO'  # Options: DEBUG, INFO, WARNING, ERROR

    # ====== ADVANCED SETTINGS ======
    SESSION_NAME = 'session'  # Telegram session file name
    CSV_ENCODING = 'utf-8'  # CSV file encoding

    @classmethod
    def load_from_file(cls, config_file='config.json'):
        """
        Load configuration from a JSON file

        Example config.json:
        {
            "CHANNEL_USERNAME": "some_other_channel",
            "SEARCH_PHRASE": "different search term",
            "OPENAI_MODEL": "gpt-4o",
            "MESSAGE_LIMIT": null,
            "USE_INCREMENTAL": true,
            "LOG_LEVEL": "DEBUG"
        }
        """
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                print(f"✅ Loaded configuration from {config_file}")

                # Update class attributes with values from file
                for key, value in config_data.items():
                    if hasattr(cls, key):
                        setattr(cls, key, value)
                        print(f"   {key} = {value}")
                    else:
                        print(f"⚠️  Unknown config key: {key}")

            except Exception as e:
                print(f"❌ Error loading config file {config_file}: {e}")
                print("   Using default configuration...")
        else:
            print(f"📄 No config file found at {config_file}, using default settings")

    @classmethod
    def load_from_env(cls):
        """Load configuration from environment variables"""
        env_mappings = {
            'TELEGRAM_CHANNEL': 'CHANNEL_USERNAME',
            'TELEGRAM_SEARCH_PHRASE': 'SEARCH_PHRASE',
            'OPENAI_MODEL': 'OPENAI_MODEL',
            'MESSAGE_LIMIT': 'MESSAGE_LIMIT',
            'USE_INCREMENTAL': 'USE_INCREMENTAL',
            'OUTPUT_FILE': 'OUTPUT_FILE',
            'LOG_LEVEL': 'LOG_LEVEL',
            'REQUEST_DELAY': 'REQUEST_DELAY',
        }

        loaded_from_env = []
        for env_var, config_attr in env_mappings.items():
            if env_var in os.environ:
                value = os.environ[env_var]

                # Convert string values to appropriate types
                if config_attr in ['MESSAGE_LIMIT'] and value.lower() in ['none', 'null', '']:
                    value = None
                elif config_attr in ['MESSAGE_LIMIT', 'MAX_TOKENS', 'MAX_CONCURRENT_REQUESTS', 'RETRY_MAX_TRIES',
                                     'RETRY_MAX_TIME']:
                    value = int(value) if value and value.lower() not in ['none', 'null'] else None
                elif config_attr in ['REQUEST_DELAY', 'TEMPERATURE']:
                    value = float(value)
                elif config_attr in ['USE_INCREMENTAL']:
                    value = value.lower() in ['true', '1', 'yes', 'on']

                setattr(cls, config_attr, value)
                loaded_from_env.append(f"{config_attr} = {value}")

        if loaded_from_env:
            print("🌍 Loaded configuration from environment variables:")
            for item in loaded_from_env:
                print(f"   {item}")

    @classmethod
    def save_example_config(cls, filename='config.example.json'):
        """Save an example configuration file"""
        example_config = {
            "CHANNEL_USERNAME": cls.CHANNEL_USERNAME,
            "SEARCH_PHRASE": cls.SEARCH_PHRASE,
            "OPENAI_MODEL": cls.OPENAI_MODEL,
            "MESSAGE_LIMIT": cls.MESSAGE_LIMIT,
            "USE_INCREMENTAL": cls.USE_INCREMENTAL,
            "REQUEST_DELAY": cls.REQUEST_DELAY,
            "OUTPUT_FILE": cls.OUTPUT_FILE,
            "LOG_LEVEL": cls.LOG_LEVEL,
            "MAX_TOKENS": cls.MAX_TOKENS,
            "TEMPERATURE": cls.TEMPERATURE,
            "MAX_CONCURRENT_REQUESTS": cls.MAX_CONCURRENT_REQUESTS,
            "_comment": "Copy this to config.json and modify as needed. Set MESSAGE_LIMIT to null for unlimited."
        }

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(example_config, f, indent=2, ensure_ascii=False)
            print(f"💾 Saved example configuration to {filename}")
        except Exception as e:
            print(f"❌ Error saving example config: {e}")

    @classmethod
    def print_current_config(cls):
        """Print the current configuration"""
        print("\n📋 Current Configuration:")
        print("=" * 50)
        print(f"🎯 Channel: {cls.CHANNEL_USERNAME}")
        print(f"🔍 Search phrase: '{cls.SEARCH_PHRASE}'")
        print(f"🤖 OpenAI model: {cls.OPENAI_MODEL}")
        print(f"📊 Message limit: {cls.MESSAGE_LIMIT if cls.MESSAGE_LIMIT else 'Unlimited'}")
        print(f"🔄 Processing mode: {'Incremental' if cls.USE_INCREMENTAL else 'Batch'}")
        print(f"⏱️  Request delay: {cls.REQUEST_DELAY}s")
        print(f"💾 Output file: {cls.OUTPUT_FILE}")
        print(f"📝 Log level: {cls.LOG_LEVEL}")
        print("=" * 50)

    @classmethod
    def get_logging_level(cls):
        """Convert string log level to logging constant"""
        levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        return levels.get(cls.LOG_LEVEL.upper(), logging.INFO)


# Load configuration on import
# Priority: config.json > environment variables > defaults
Config.load_from_file()
Config.load_from_env()