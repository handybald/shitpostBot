#!/usr/bin/env python3
"""
Setup Credentials for ShitPostBot

This script helps you add the necessary credentials to .env file.
Run this before your first deployment.

Required Credentials:
1. Instagram (Graph API)
2. Telegram Bot Token
3. OpenAI API Key
4. AWS S3 Credentials (optional but recommended)
5. Your Telegram User ID (for admin control)
"""

import os
import sys
from pathlib import Path

def check_env_file():
    """Check if .env exists and what's already configured."""
    env_path = Path(".env")

    if not env_path.exists():
        print("❌ .env file not found!")
        print("   Please run: cp .env.example .env")
        return False

    with open(env_path) as f:
        content = f.read()

    required_vars = {
        "TELEGRAM_BOT_TOKEN": "Telegram bot token",
        "OPENAI_API_KEY": "OpenAI API key",
        "IG_USER_ID": "Instagram Business Account ID",
        "IG_ACCESS_TOKEN": "Instagram Graph API access token",
        "IG_APP_ID": "Instagram App ID",
        "IG_APP_SECRET": "Instagram App Secret",
    }

    optional_vars = {
        "AWS_ACCESS_KEY_ID": "AWS Access Key ID",
        "AWS_SECRET_ACCESS_KEY": "AWS Secret Access Key",
        "S3_BUCKET_NAME": "S3 Bucket Name",
        "AWS_REGION": "AWS Region",
    }

    print("\n📋 Credentials Status:\n")

    missing_required = []
    missing_optional = []

    for var, desc in required_vars.items():
        if f"{var}=" in content and not content.split(f"{var}=")[1].startswith("$"):
            # Check if has actual value (not placeholder)
            value = content.split(f"{var}=")[1].split("\n")[0].strip()
            if value and value != "your_value":
                print(f"✅ {var:30} → Configured")
            else:
                print(f"❌ {var:30} → Missing (REQUIRED)")
                missing_required.append(var)
        else:
            print(f"❌ {var:30} → Missing (REQUIRED)")
            missing_required.append(var)

    print()

    for var, desc in optional_vars.items():
        if f"{var}=" in content:
            value = content.split(f"{var}=")[1].split("\n")[0].strip()
            if value and value != "your_value":
                print(f"✅ {var:30} → Configured")
            else:
                print(f"⚠️  {var:30} → Missing (optional)")
                missing_optional.append(var)
        else:
            print(f"⚠️  {var:30} → Missing (optional)")
            missing_optional.append(var)

    print("\n" + "="*60)

    if missing_required:
        print(f"\n🔴 {len(missing_required)} REQUIRED credentials missing:")
        for var in missing_required:
            print(f"   - {var}")
        return False
    elif missing_optional:
        print(f"\n🟡 {len(missing_optional)} optional credentials missing")
        print("   (System will work but with limited functionality)")
        return True
    else:
        print("\n✅ All required credentials configured!")
        return True


def get_telegram_user_id():
    """Help user find their Telegram user ID."""
    print("\n" + "="*60)
    print("📱 Getting Your Telegram User ID\n")
    print("Steps:")
    print("1. Open Telegram")
    print("2. Search for @userinfobot")
    print("3. Send /start")
    print("4. Copy your User ID number (e.g., 123456789)")
    print("\nAlternatively, open this bot and it will tell you:")
    print("   https://t.me/userinfobot")
    return input("\nEnter your Telegram User ID: ").strip()


def show_credentials_guide():
    """Show where to get each credential."""
    guide = """
📚 CREDENTIALS GUIDE

1️⃣  TELEGRAM_BOT_TOKEN
   - Go to Telegram and search @BotFather
   - Send: /newbot
   - Follow instructions to create a bot
   - Copy the token (looks like: 123456789:ABCdefGHIjklmnoPQRstuvWXYZ_1234567890)
   - Add to .env: TELEGRAM_BOT_TOKEN=your_token_here

2️⃣  OPENAI_API_KEY
   - Go to https://platform.openai.com/api-keys
   - Click "Create new secret key"
   - Copy the key (looks like: sk-proj-...)
   - Add to .env: OPENAI_API_KEY=your_key_here
   - Note: You need an OpenAI account with billing enabled

3️⃣  Instagram Credentials (Graph API)
   - Go to https://developers.facebook.com/
   - Create an App (if you don't have one)
   - Go to App Settings → Basic → Copy App ID and Secret
   - Create an Instagram Business Account
   - Get Business Account ID and Access Token from Meta App Dashboard
   - Add to .env:
     IG_APP_ID=your_app_id
     IG_APP_SECRET=your_app_secret
     IG_USER_ID=your_business_account_id
     IG_ACCESS_TOKEN=your_access_token

4️⃣  AWS S3 Credentials (Optional but Recommended)
   - Go to AWS Console: https://console.aws.amazon.com
   - Create S3 Bucket for storing videos
   - Create IAM User with S3 access
   - Generate Access Key ID and Secret Access Key
   - Add to .env:
     AWS_ACCESS_KEY_ID=your_key
     AWS_SECRET_ACCESS_KEY=your_secret
     S3_BUCKET_NAME=your_bucket_name
     AWS_REGION=us-east-1

5️⃣  Your Telegram User ID
   - Open Telegram and search @userinfobot
   - Send /start
   - It will show your User ID
   - You'll need this to control the bot
   - In config/config.yaml, update:
     telegram:
       admin_users: [YOUR_USER_ID]

⚠️  SECURITY NOTES:
   - NEVER commit .env to git
   - NEVER share your tokens/keys
   - Rotate keys regularly
   - Use strong, unique API keys
   - Keep .env file permission restricted: chmod 600 .env
"""
    print(guide)


def main():
    print("\n" + "="*60)
    print("🤖 ShitPostBot - Credentials Setup")
    print("="*60)

    # Check current status
    is_ready = check_env_file()

    if not is_ready:
        print("\n" + "="*60)
        response = input("\n📖 Would you like to see the credentials guide? (y/n): ").lower()
        if response == 'y':
            show_credentials_guide()

        print("\n" + "="*60)
        print("\n⏭️  Next Steps:")
        print("1. Get the credentials using the guide above")
        print("2. Edit .env file with your credentials")
        print("3. Run this script again to verify")
        print("\nTo edit .env:")
        print("   nano .env  (or your favorite editor)")
        sys.exit(1)
    else:
        print("\n✅ All required credentials are configured!")

        # Ask for Telegram admin ID
        print("\n" + "="*60)
        telegram_id = get_telegram_user_id()

        if telegram_id:
            # Update config.yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path) as f:
                    config_content = f.read()

                # Update admin_users line
                if "admin_users: []" in config_content:
                    config_content = config_content.replace(
                        "admin_users: []",
                        f"admin_users: [{telegram_id}]"
                    )
                    with open(config_path, 'w') as f:
                        f.write(config_content)
                    print(f"\n✅ Updated config.yaml with Telegram ID: {telegram_id}")
                else:
                    print(f"\n⚠️  Couldn't auto-update config.yaml")
                    print(f"   Please manually update admin_users: [{telegram_id}]")

        print("\n" + "="*60)
        print("\n🚀 You're ready to deploy!")
        print("\nRun the bot with:")
        print("   source venv/bin/activate")
        print("   python3 main.py")
        print("\nThen open Telegram and send /start to your bot")
        print("="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
