#!/usr/bin/env python3
"""
Quick setup: Generate test assets + seed database in one go.
Run this once after cloning the project to be ready to generate content.
"""

import subprocess
import sys

print("🚀 ShitPostBot Quick Setup\n")
print("="*60)

# Step 1: Generate test assets
print("\n1️⃣  Generating test assets (videos, music, quotes)...")
print("-"*60)
try:
    result = subprocess.run([sys.executable, "generate_test_assets.py"], check=True)
    print("✓ Test assets generated successfully\n")
except subprocess.CalledProcessError as e:
    print(f"✗ Failed to generate test assets: {e}\n")
    sys.exit(1)

# Step 2: Seed database
print("\n2️⃣  Seeding database with test assets...")
print("-"*60)
try:
    result = subprocess.run([sys.executable, "seed_database.py"], check=True)
    print("✓ Database seeded successfully\n")
except subprocess.CalledProcessError as e:
    print(f"✗ Failed to seed database: {e}\n")
    sys.exit(1)

# Done!
print("\n" + "="*60)
print("✅ Quick Setup Complete!")
print("="*60)

print("\n📊 Your bot now has:")
print("  • 5 test videos (different themes)")
print("  • 5 test audio tracks (different energy levels)")
print("  • 20 motivational quotes")
print("  • Everything configured and ready to generate")

print("\n🚀 Next steps:")
print("  1. Start the bot: python main.py")
print("  2. Open Telegram and send: /generate 3")
print("  3. Check /queue to see your generated reels")
print("  4. Send /approve <id> to schedule for posting")

print("\n💡 Pro tip:")
print("  You can add your own videos/music to data/raw/")
print("  The bot will automatically discover and use them")

print("\n" + "="*60)
