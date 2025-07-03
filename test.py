import asyncio
import csv
import json
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import logging
import aiohttp
import time
from typing import List, Dict, Optional
import backoff

# Set up logging with UTF-8 encoding for Windows
import sys
import os

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


logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_scraper.log', encoding='utf-8'),
        UTF8StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CREDENTIALS_FILE = 'src/credentials.json'
OPENAI_MODEL = 'gpt-4o-mini'  # Or 'gpt-4-turbo', 'gpt-3.5-turbo', etc.


def load_credentials():
    """Load credentials from file or prompt user to enter them"""
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                creds = json.load(f)

            # Validate that all required fields exist
            required_fields = ['api_id', 'api_hash', 'phone_number', 'openai_api_key']
            if all(field in creds for field in required_fields):
                print("✅ Loaded credentials from credentials.json")
                return creds
            else:
                print("❌ credentials.json is missing required fields")

        except (json.JSONDecodeError, Exception) as e:
            print(f"❌ Error reading credentials.json: {e}")

    # If we get here, we need to prompt for credentials
    print("\n🔐 Please enter your credentials:")
    print("(These will be saved to credentials.json for future use)")

    creds = {}
    creds['api_id'] = input('Telegram API ID (from https://my.telegram.org): ').strip()
    creds['api_hash'] = input('Telegram API Hash (from https://my.telegram.org): ').strip()
    creds['phone_number'] = input('Phone number (with country code, e.g., +1234567890): ').strip()
    creds['openai_api_key'] = input('OpenAI API Key: ').strip()

    # Validate inputs
    if not all(creds.values()):
        print("❌ All fields are required!")
        return None

    # Convert API_ID to integer
    try:
        creds['api_id'] = int(creds['api_id'])
    except ValueError:
        print("❌ API ID must be a number!")
        return None

    # Save credentials
    try:
        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(creds, f, indent=2)

        # Set file permissions to be readable only by owner (Unix-like systems)
        if not sys.platform.startswith('win'):
            os.chmod(CREDENTIALS_FILE, 0o600)

        print(f"✅ Credentials saved to {CREDENTIALS_FILE}")
        print("⚠️  Keep this file secure and don't share it!")

    except Exception as e:
        print(f"❌ Error saving credentials: {e}")
        return None

    return creds


def get_credentials():
    """Get credentials with option to reset them"""
    if os.path.exists(CREDENTIALS_FILE):
        reset = input(f"\nCredentials file exists. Reset credentials? (y/N): ").strip().lower()
        if reset in ['y', 'yes']:
            os.remove(CREDENTIALS_FILE)
            print("🗑️  Removed existing credentials file")

    return load_credentials()


CHANNEL_USERNAME = 'kpszsu'  # Ukraine Air Force channel
SEARCH_PHRASE = 'У ніч на'  # The phrase to search for
OUTPUT_FILE = 'ukraine_airforce_updates.csv'

# OpenAI processing settings
MAX_CONCURRENT_REQUESTS = 5  # Adjust based on your rate limits
REQUEST_DELAY = 1  # Seconds between requests to avoid rate limiting

# Your prompt for OpenAI
ANALYSIS_PROMPT = """You will be given a military update text reporting attacks on Ukraine by various aerial assets (drones, missiles, aircraft, etc.). Your task is to analyze the text carefully and extract the total number of attacking assets by type and subtype as of the report date.

**Requirements:**

- Extract and return **only one JSON object** matching this exact structure:

```json
{{
  "date": "YYYY-MM-DD",
  "counts": [
    {{
      "type": "string (e.g. drones, missiles, aircraft, fighter_aircraft, attack_drones)",
      "number": integer,
      "additional_details": "string describing key details about the attack or losses",
      "subtypes": [                          // Optional field; include only if subtype details are present
        {{
          "subtype": "string (e.g. Shahed-136, Iskander-M)",
          "number": integer,
          "additional_details": "string with subtype-specific info"
        }},
        ...
      ]
    }},
    ...
  ]
}}
```

* The `date` field must correspond to the date of the report or attack described.

* The `counts` array must list each distinct attacking asset type found in the text with its total number (integer).

* If specific subtypes with counts are mentioned, include a `subtypes` array inside the relevant asset object listing each subtype, its count, and relevant additional details.

* The `additional_details` field should summarize important context relevant to that type, such as locations, attack origins, or general outcomes (e.g., "shot down by air defense", "attack from Shahed drones", "no aircraft mentioned").

* **Do not return any text other than this JSON object.**

* If the input text does not contain sufficient information to build the JSON object as specified, respond with a single literal value: `NULL` (without quotes).

* Be strict: do not add extra fields or deviate from the structure.

* Do not provide explanations, commentary, or any other text.

Now analyze the following input and return the JSON or NULL:

{message_text}"""


class OpenAIProcessor:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        max_time=60
    )
    async def process_message(self, message_text: str, message_id: int) -> Optional[Dict]:
        """Process a message through OpenAI API with retry logic"""
        try:
            prompt = ANALYSIS_PROMPT.format(message_text=message_text)

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a military analyst. Analyze the provided Ukrainian military update text and extract attack data in the specified JSON format. Return ONLY the JSON object, no other text."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0,
                "max_tokens": 2000,
                "response_format": {"type": "json_object"}
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            logger.info(f"Processing message {message_id} with OpenAI...")

            async with self.session.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
            ) as response:

                if response.status == 200:
                    result = await response.json()
                    content = result['choices'][0]['message']['content'].strip()

                    logger.debug(f"Message {message_id}: Raw OpenAI response length: {len(content)}")
                    logger.debug(f"Message {message_id}: First 100 chars: {repr(content[:100])}")

                    # Try to parse as JSON
                    if content == "NULL":
                        logger.info(f"Message {message_id}: OpenAI returned NULL (insufficient data)")
                        return None

                    # Clean the content - sometimes OpenAI adds markdown formatting or extra whitespace
                    original_content = content

                    # Remove markdown code blocks if present
                    if content.startswith('```json'):
                        content = content[7:]
                    elif content.startswith('```'):
                        content = content[3:]
                    if content.endswith('```'):
                        content = content[:-3]

                    # Strip whitespace again
                    content = content.strip()

                    # Try to find JSON object boundaries
                    start_idx = content.find('{')
                    end_idx = content.rfind('}')

                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        content = content[start_idx:end_idx + 1]

                    try:
                        parsed_json = json.loads(content)
                        logger.info(f"Message {message_id}: Successfully processed by OpenAI")
                        return parsed_json

                    except json.JSONDecodeError as e:
                        logger.error(f"Message {message_id}: JSON parse error: {e}")
                        logger.error(f"Message {message_id}: Cleaned content: {repr(content[:200])}")
                        logger.error(f"Message {message_id}: Original content: {repr(original_content[:200])}")

                        # Last resort: try to manually extract JSON
                        try:
                            # Look for lines that might form valid JSON
                            lines = content.split('\n')
                            json_lines = []
                            brace_count = 0
                            started = False

                            for line in lines:
                                stripped = line.strip()
                                if not started and stripped.startswith('{'):
                                    started = True

                                if started:
                                    json_lines.append(line)
                                    brace_count += line.count('{') - line.count('}')

                                    if brace_count == 0 and started:
                                        break

                            if json_lines:
                                manual_content = '\n'.join(json_lines)
                                parsed_json = json.loads(manual_content)
                                logger.info(f"Message {message_id}: Successfully parsed after manual cleaning")
                                return parsed_json

                        except Exception as manual_e:
                            logger.error(f"Message {message_id}: Manual parsing also failed: {manual_e}")

                        return None

                elif response.status == 429:  # Rate limit
                    error_text = await response.text()
                    logger.warning(f"Message {message_id}: Rate limited. Response: {error_text}")
                    # Backoff decorator will retry
                    raise aiohttp.ClientError(f"Rate limited: {error_text}")

                else:
                    error_text = await response.text()
                    logger.error(f"Message {message_id}: OpenAI API error {response.status}: {error_text}")
                    return None

        except Exception as e:
            logger.error(f"Message {message_id}: Unexpected error in OpenAI processing: {e}")
            return None


class TelegramScraper:
    def __init__(self, api_id, api_hash, phone_number):
        self.client = TelegramClient('session', api_id, api_hash)
        self.phone_number = phone_number

    async def connect_and_auth(self):
        """Connect to Telegram and authenticate"""
        await self.client.start()

        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone_number)
            code = input('Enter the code you received: ')
            try:
                await self.client.sign_in(self.phone_number, code)
            except SessionPasswordNeededError:
                password = input('Two-factor authentication enabled. Please enter your password: ')
                await self.client.sign_in(password=password)

    async def get_channel_entity(self, channel_username):
        """Get the channel entity"""
        try:
            entity = await self.client.get_entity(channel_username)
            logger.info(f"Found channel: {entity.title}")
            return entity
        except Exception as e:
            logger.error(f"Error getting channel entity: {e}")
            return None

    async def scrape_messages(self, channel_entity, search_phrase, limit=None):
        """Scrape messages containing the search phrase"""
        messages_data = []
        count = 0

        logger.info(f"Starting to scrape messages containing '{search_phrase}'...")

        async for message in self.client.iter_messages(channel_entity, limit=limit):
            if message.text and search_phrase in message.text:
                count += 1
                logger.info(f"Found message #{count} - ID: {message.id}, Date: {message.date}")

                # Extract basic message data
                message_data = {
                    'channel_username': channel_entity.username,
                    'channel_title': channel_entity.title,
                    'channel_id': channel_entity.id,
                    'message_id': message.id,
                    'date': message.date.isoformat() if message.date else None,
                    'message_text': message.text,
                    'views': getattr(message, 'views', None),
                    'forwards': getattr(message, 'forwards', None),
                    'replies': getattr(message.replies, 'replies', None) if message.replies else None,
                    'edit_date': message.edit_date.isoformat() if message.edit_date else None,
                    'grouped_id': message.grouped_id,
                    'from_id': message.from_id.user_id if message.from_id else None,
                    'post_author': message.post_author,
                    'full_message_object': json.dumps(message.to_dict(), default=str, ensure_ascii=False),
                    # These will be filled by OpenAI processing
                    'openai_analysis': None,
                    'openai_processed': False,
                    'openai_error': None
                }

                messages_data.append(message_data)

        logger.info(f"Found {count} messages containing '{search_phrase}'")
        return messages_data

    async def process_with_openai_batch(self, messages_data: List[Dict], processor: OpenAIProcessor):
        """Process messages with OpenAI using controlled concurrency"""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def process_single_message(message_data: Dict):
            async with semaphore:
                try:
                    # Add delay to respect rate limits
                    await asyncio.sleep(REQUEST_DELAY)

                    result = await processor.process_message(
                        message_data['message_text'],
                        message_data['message_id']
                    )

                    if result is not None:
                        message_data['openai_analysis'] = json.dumps(result, ensure_ascii=False)
                        message_data['openai_processed'] = True
                        logger.info(f"Successfully processed message {message_data['message_id']}")
                    else:
                        message_data['openai_analysis'] = None
                        message_data['openai_processed'] = False
                        message_data['openai_error'] = "Failed to process or returned NULL"
                        logger.warning(f"Failed to process message {message_data['message_id']}")

                except Exception as e:
                    message_data['openai_analysis'] = None
                    message_data['openai_processed'] = False
                    message_data['openai_error'] = str(e)
                    logger.error(f"Error processing message {message_data['message_id']}: {e}")

        # Create tasks for all messages
        tasks = [process_single_message(msg) for msg in messages_data]

        logger.info(f"Starting to process {len(tasks)} messages with OpenAI (max {MAX_CONCURRENT_REQUESTS} concurrent)")

        # Execute all tasks
        await asyncio.gather(*tasks, return_exceptions=True)

        # Log summary
        successful = sum(1 for msg in messages_data if msg['openai_processed'])
        failed = len(messages_data) - successful
        logger.info(f"OpenAI processing complete: {successful} successful, {failed} failed")

    async def save_to_csv(self, messages_data: List[Dict], filename: str):
        """Save messages data to CSV file"""
        if not messages_data:
            logger.warning("No data to save")
            return

        fieldnames = [
            'channel_username', 'channel_title', 'channel_id',
            'message_id', 'date', 'message_text', 'views', 'forwards',
            'replies', 'edit_date', 'grouped_id', 'from_id', 'post_author',
            'openai_analysis', 'openai_processed', 'openai_error',
            'full_message_object'
        ]

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(messages_data)

        logger.info(f"Saved {len(messages_data)} messages to {filename}")

    async def run_scraper(self, channel_username: str, search_phrase: str, output_file: str, openai_api_key: str,
                          message_limit: Optional[int] = None):
        """Main method to run the scraper with OpenAI processing"""
        try:
            # Connect and authenticate
            await self.connect_and_auth()

            # Get channel entity
            channel_entity = await self.get_channel_entity(channel_username)
            if not channel_entity:
                return

            # Scrape messages
            messages_data = await self.scrape_messages(
                channel_entity, search_phrase, limit=message_limit
            )

            if not messages_data:
                logger.info("No messages found to process")
                return

            # Process with OpenAI
            async with OpenAIProcessor(openai_api_key, OPENAI_MODEL) as processor:
                await self.process_with_openai_batch(messages_data, processor)

            # Save to CSV
            await self.save_to_csv(messages_data, output_file)

            # Print summary
            total_messages = len(messages_data)
            processed_successfully = sum(1 for msg in messages_data if msg['openai_processed'])
            logger.info(f"\n=== FINAL SUMMARY ===")
            logger.info(f"Total messages scraped: {total_messages}")
            logger.info(f"Successfully processed by OpenAI: {processed_successfully}")
            logger.info(f"Failed OpenAI processing: {total_messages - processed_successfully}")
            logger.info(f"Results saved to: {output_file}")

        except Exception as e:
            logger.error(f"Error during scraping: {e}")
        finally:
            await self.client.disconnect()


async def main():
    """Main function"""
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
    logger.info("Starting Telegram scraper...")
    logger.info(f"Target channel: {CHANNEL_USERNAME}")
    logger.info(f"Search phrase: {SEARCH_PHRASE}")
    logger.info(f"OpenAI model: {OPENAI_MODEL}")

    # Create scraper instance
    scraper = TelegramScraper(api_id, api_hash, phone_number)

    # Run scraper with OpenAI processing
    await scraper.run_scraper(
        channel_username=CHANNEL_USERNAME,
        search_phrase=SEARCH_PHRASE,
        output_file=OUTPUT_FILE,
        openai_api_key=openai_api_key,
        message_limit=1000  # Adjust as needed, or set to None for all messages
    )


if __name__ == "__main__":
    asyncio.run(main())