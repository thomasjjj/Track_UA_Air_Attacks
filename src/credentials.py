import os
import json
import sys

CREDENTIALS_FILE = 'credentials.json'

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