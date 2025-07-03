import asyncio
import csv
import json
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import logging
import aiohttp
from typing import List, Dict, Optional
import backoff
from src.credentials import get_credentials
from src.prompt import ANALYSIS_PROMPT
from config import Config

# Set up logging with UTF-8 encoding for Windows
import sys
import os

# Fix Windows console encoding for Ukrainian text
if sys.platform.startswith('win'):
    os.system('chcp 65001 > nul')

logger = logging.getLogger(__name__)

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
        max_tries=Config.RETRY_MAX_TRIES,
        max_time=Config.RETRY_MAX_TIME
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
                "temperature": Config.TEMPERATURE,
                "max_tokens": Config.MAX_TOKENS,
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