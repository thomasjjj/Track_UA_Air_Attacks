import asyncio
import csv
import json
import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import logging
import aiohttp
from typing import List, Dict, Optional, Set
import backoff
from src.credentials import get_credentials
from src.prompt import ANALYSIS_PROMPT
from src.openai_processor import OpenAIProcessor
from config import Config

# Set up logging with UTF-8 encoding for Windows
import sys

# Fix Windows console encoding for Ukrainian text
if sys.platform.startswith('win'):
    os.system('chcp 65001 > nul')

logger = logging.getLogger(__name__)


class TelegramScraper:
    def __init__(self, api_id, api_hash, phone_number):
        self.client = TelegramClient(Config.SESSION_NAME, api_id, api_hash)
        self.phone_number = phone_number
        self.processed_message_ids: Set[int] = set()

    def _get_csv_fieldnames(self):
        """Get the CSV fieldnames"""
        return [
            'channel_username', 'channel_title', 'channel_id',
            'message_id', 'date', 'message_text', 'views', 'forwards',
            'replies', 'edit_date', 'grouped_id', 'from_id', 'post_author',
            'openai_analysis', 'openai_processed', 'openai_error',
            'full_message_object'
        ]

    def _load_existing_csv(self, filename: str) -> tuple[Set[int], List[Dict]]:
        """Load existing CSV and return (processed_ids, unprocessed_messages)"""
        processed_ids = set()
        unprocessed_messages = []

        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        if row.get('message_id'):
                            try:
                                message_id = int(row['message_id'])
                                processed_ids.add(message_id)

                                # Check if OpenAI processing is complete
                                openai_processed = row.get('openai_processed', '').lower()
                                if openai_processed not in ['true', '1', 'yes']:
                                    # This message needs OpenAI processing
                                    unprocessed_messages.append({
                                        'channel_username': row.get('channel_username'),
                                        'channel_title': row.get('channel_title'),
                                        'channel_id': int(row.get('channel_id', 0)) if row.get('channel_id') else None,
                                        'message_id': message_id,
                                        'date': row.get('date'),
                                        'message_text': row.get('message_text'),
                                        'views': int(row.get('views', 0)) if row.get('views') else None,
                                        'forwards': int(row.get('forwards', 0)) if row.get('forwards') else None,
                                        'replies': int(row.get('replies', 0)) if row.get('replies') else None,
                                        'edit_date': row.get('edit_date'),
                                        'grouped_id': row.get('grouped_id'),
                                        'from_id': int(row.get('from_id', 0)) if row.get('from_id') else None,
                                        'post_author': row.get('post_author'),
                                        'full_message_object': row.get('full_message_object'),
                                        'openai_analysis': None,
                                        'openai_processed': False,
                                        'openai_error': None
                                    })
                            except ValueError:
                                continue

                logger.info(f"Found {len(processed_ids)} existing messages in {filename}")
                if unprocessed_messages:
                    logger.info(f"Found {len(unprocessed_messages)} messages that need OpenAI processing")

            except Exception as e:
                logger.error(f"Error reading existing CSV: {e}")

        return processed_ids, unprocessed_messages

    def _initialize_csv(self, filename: str):
        """Initialize CSV file with headers if it doesn't exist"""
        if not os.path.exists(filename):
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self._get_csv_fieldnames())
                writer.writeheader()
            logger.info(f"Created new CSV file: {filename}")

    def _append_to_csv(self, filename: str, message_data: Dict):
        """Append a single message to CSV file"""
        try:
            with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self._get_csv_fieldnames())
                writer.writerow(message_data)
            logger.debug(f"Appended message {message_data['message_id']} to CSV")
        except Exception as e:
            logger.error(f"Error appending to CSV: {e}")

    def _update_message_in_csv(self, filename: str, updated_message: Dict):
        """Update a specific message in the CSV file"""
        try:
            # Read all rows
            rows = []
            with open(filename, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                fieldnames = reader.fieldnames
                rows = list(reader)

            # Update the specific message
            message_id = str(updated_message['message_id'])
            for i, row in enumerate(rows):
                if row.get('message_id') == message_id:
                    # Update this row with the new data
                    for key, value in updated_message.items():
                        row[key] = value
                    break

            # Write back all rows
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            logger.debug(f"Updated message {message_id} in CSV")

        except Exception as e:
            logger.error(f"Error updating message in CSV: {e}")

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

    async def scrape_messages_hybrid(self, channel_entity, search_phrase: str, output_file: str, limit=None):
        """Scrape messages and save them immediately (without OpenAI processing yet)"""

        # Load existing data
        self.processed_message_ids, _ = self._load_existing_csv(output_file)

        # Initialize CSV if it doesn't exist
        self._initialize_csv(output_file)

        messages_data = []
        count = 0
        new_messages = 0

        logger.info(f"Starting to scrape messages containing '{search_phrase}'...")
        logger.info(f"Skipping {len(self.processed_message_ids)} already saved messages")

        try:
            async for message in self.client.iter_messages(channel_entity, limit=limit):
                if message.text and search_phrase in message.text:
                    count += 1

                    # Skip if already saved
                    if message.id in self.processed_message_ids:
                        logger.debug(f"⏭️ Skipping already saved message {message.id}")
                        continue

                    logger.info(f"📨 Found new message #{count} - ID: {message.id}, Date: {message.date}")

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
                        # OpenAI fields - will be filled later
                        'openai_analysis': None,
                        'openai_processed': False,
                        'openai_error': None
                    }

                    # Save to CSV immediately (without OpenAI processing)
                    self._append_to_csv(output_file, message_data)
                    messages_data.append(message_data)

                    # Add to processed set
                    self.processed_message_ids.add(message.id)
                    new_messages += 1

                    logger.info(f"💾 Saved message {message.id} to {output_file} (New messages: {new_messages})")

        except KeyboardInterrupt:
            logger.info(f"\n⏹️ Interrupted during message collection")
            logger.info(f"📊 Collected {new_messages} new messages in this session")
            logger.info(f"💾 All messages saved to {output_file}")
            logger.info(f"🔄 You can resume OpenAI processing by running the script again")
            raise

        logger.info(f"\n✅ Message collection completed!")
        logger.info(f"📊 Total messages found: {count}")
        logger.info(f"📊 New messages collected: {new_messages}")
        logger.info(f"💾 All messages saved to: {output_file}")

        return messages_data

    async def process_unprocessed_messages_with_openai(self, output_file: str, processor: OpenAIProcessor):
        """Process messages that haven't been processed by OpenAI yet"""

        # Load messages that need processing
        _, unprocessed_messages = self._load_existing_csv(output_file)

        if not unprocessed_messages:
            logger.info("✅ All messages already processed by OpenAI")
            return

        logger.info(f"🤖 Found {len(unprocessed_messages)} messages that need OpenAI processing")

        # Process with controlled concurrency
        semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_REQUESTS)
        processed_count = 0
        failed_count = 0

        async def process_single_message(message_data: Dict):
            nonlocal processed_count, failed_count
            async with semaphore:
                try:
                    # Add delay to respect rate limits
                    await asyncio.sleep(Config.REQUEST_DELAY)

                    result = await processor.process_message(
                        message_data['message_text'],
                        message_data['message_id']
                    )

                    if result is not None:
                        message_data['openai_analysis'] = json.dumps(result, ensure_ascii=False)
                        message_data['openai_processed'] = True
                        message_data['openai_error'] = None
                        processed_count += 1
                        logger.info(
                            f"✅ Processed message {message_data['message_id']} ({processed_count}/{len(unprocessed_messages)})")
                    else:
                        message_data['openai_analysis'] = None
                        message_data['openai_processed'] = False
                        message_data['openai_error'] = "Failed to process or returned NULL"
                        failed_count += 1
                        logger.warning(f"⚠️ Failed to process message {message_data['message_id']}")

                    # Update the CSV file with the processed result
                    self._update_message_in_csv(output_file, message_data)

                except Exception as e:
                    message_data['openai_analysis'] = None
                    message_data['openai_processed'] = False
                    message_data['openai_error'] = str(e)
                    failed_count += 1
                    logger.error(f"❌ Error processing message {message_data['message_id']}: {e}")

                    # Still update CSV with error info
                    self._update_message_in_csv(output_file, message_data)

        # Create tasks for all unprocessed messages
        tasks = [process_single_message(msg) for msg in unprocessed_messages]

        logger.info(
            f"🚀 Starting OpenAI processing of {len(tasks)} messages (max {Config.MAX_CONCURRENT_REQUESTS} concurrent)")

        try:
            # Execute all tasks
            await asyncio.gather(*tasks, return_exceptions=True)
        except KeyboardInterrupt:
            logger.info(f"\n⏹️ Interrupted during OpenAI processing")
            logger.info(f"📊 Processed {processed_count} messages before interruption")
            logger.info(f"🔄 You can resume by running the script again")
            raise

        # Log summary
        logger.info(f"\n✅ OpenAI processing complete!")
        logger.info(f"📊 Successfully processed: {processed_count}")
        logger.info(f"📊 Failed: {failed_count}")
        logger.info(f"💾 Results saved to: {output_file}")

    async def scrape_messages_incremental(
            self,
            channel_entity,
            search_phrase: str,
            output_file: str,
            processor: OpenAIProcessor,
            limit: Optional[int] = None,
            delay_between_requests: float = 1.0
    ):
        """Original incremental processing method (kept for backward compatibility)"""

        # Load existing processed message IDs
        self.processed_message_ids, _ = self._load_existing_csv(output_file)

        # Initialize CSV if it doesn't exist
        self._initialize_csv(output_file)

        count = 0
        processed_count = 0
        skipped_count = len(self.processed_message_ids)

        logger.info(f"Starting incremental scraping for messages containing '{search_phrase}'...")
        logger.info(f"Skipping {skipped_count} already processed messages")

        try:
            async for message in self.client.iter_messages(channel_entity, limit=limit):
                if message.text and search_phrase in message.text:
                    count += 1

                    # Skip if already processed
                    if message.id in self.processed_message_ids:
                        logger.debug(f"⏭️ Skipping already processed message {message.id}")
                        continue

                    logger.info(f"📨 Found new message #{count} - ID: {message.id}, Date: {message.date}")

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

                    # Process with OpenAI immediately
                    logger.info(f"🤖 Processing message {message.id} with OpenAI...")
                    message_data = await self._process_single_message_with_openai(message_data, processor)

                    # Save to CSV immediately
                    self._append_to_csv(output_file, message_data)

                    # Add to processed set
                    self.processed_message_ids.add(message.id)
                    processed_count += 1

                    logger.info(f"💾 Saved message {message.id} to {output_file} (Total processed: {processed_count})")

                    # Add delay between requests to respect rate limits
                    if delay_between_requests > 0:
                        await asyncio.sleep(delay_between_requests)

        except KeyboardInterrupt:
            logger.info(f"\n⏹️ Interrupted by user. Progress saved to {output_file}")
            logger.info(f"📊 Processed {processed_count} new messages in this session")
            raise
        except Exception as e:
            logger.error(f"❌ Error during scraping: {e}")
            logger.info(f"📊 Processed {processed_count} messages before error")
            raise

        logger.info(f"\n✅ Incremental scraping completed!")
        logger.info(f"📊 Total messages found: {count}")
        logger.info(f"📊 New messages processed: {processed_count}")
        logger.info(f"📊 Previously processed: {skipped_count}")

    async def _process_single_message_with_openai(self, message_data: Dict, processor: OpenAIProcessor) -> Dict:
        """Process a single message with OpenAI and return updated message_data"""
        try:
            result = await processor.process_message(
                message_data['message_text'],
                message_data['message_id']
            )

            if result is not None:
                message_data['openai_analysis'] = json.dumps(result, ensure_ascii=False)
                message_data['openai_processed'] = True
                message_data['openai_error'] = None
                logger.info(f"✅ Successfully processed message {message_data['message_id']}")
            else:
                message_data['openai_analysis'] = None
                message_data['openai_processed'] = False
                message_data['openai_error'] = "Failed to process or returned NULL"
                logger.warning(f"⚠️ Failed to process message {message_data['message_id']}")

        except Exception as e:
            message_data['openai_analysis'] = None
            message_data['openai_processed'] = False
            message_data['openai_error'] = str(e)
            logger.error(f"❌ Error processing message {message_data['message_id']}: {e}")

        return message_data

    async def run_scraper(self, channel_username: str, search_phrase: str, output_file: str, openai_api_key: str,
                          message_limit: Optional[int] = None, incremental: bool = True,
                          openai_model: str = "gpt-4o-mini"):
        """Main method to run the scraper with OpenAI processing

        Args:
            incremental: If True, uses incremental processing. If False, uses hybrid batch processing.
        """
        try:
            # Connect and authenticate
            await self.connect_and_auth()

            # Get channel entity
            channel_entity = await self.get_channel_entity(channel_username)
            if not channel_entity:
                return

            # Process with OpenAI
            async with OpenAIProcessor(openai_api_key, openai_model) as processor:
                if incremental:
                    # Use incremental processing (original method)
                    logger.info("🔄 Using incremental processing mode")
                    await self.scrape_messages_incremental(
                        channel_entity=channel_entity,
                        search_phrase=search_phrase,
                        output_file=output_file,
                        processor=processor,
                        limit=message_limit,
                        delay_between_requests=Config.REQUEST_DELAY
                    )
                else:
                    # Use hybrid batch processing (new method)
                    logger.info("🔄 Using hybrid batch processing mode")

                    # Step 1: Collect and save all messages (interrupt-safe)
                    logger.info("📥 Phase 1: Collecting messages...")
                    new_messages = await self.scrape_messages_hybrid(
                        channel_entity, search_phrase, output_file, limit=message_limit
                    )

                    # Step 2: Process any unprocessed messages with OpenAI (interrupt-safe)
                    logger.info("🤖 Phase 2: Processing with OpenAI...")
                    await self.process_unprocessed_messages_with_openai(output_file, processor)

        except KeyboardInterrupt:
            logger.info("🛑 Gracefully stopping...")
        except Exception as e:
            logger.error(f"Error during scraping: {e}")
        finally:
            await self.client.disconnect()
            logger.info("🔌 Disconnected from Telegram")