#!/usr/bin/env python3
"""
Generate test assets (videos, music, quotes) for ShitPostBot.
This allows the bot to start generating content immediately without manual file uploads.
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime

# Create directories
Path("data/raw/videos").mkdir(parents=True, exist_ok=True)
Path("data/raw/music").mkdir(parents=True, exist_ok=True)

print("🎬 Generating Test Assets for ShitPostBot...\n")

# ============================================================================
# 1. GENERATE TEST VIDEOS (10 seconds each, different colors/themes)
# ============================================================================
print("📹 Generating test videos...")

videos = [
    {
        "name": "motivation_1.mp4",
        "color": "gold",
        "theme": "motivation",
        "description": "Golden motivational background"
    },
    {
        "name": "hustle_1.mp4",
        "color": "red",
        "theme": "hustle",
        "description": "Red energy background"
    },
    {
        "name": "philosophy_1.mp4",
        "color": "darkblue",
        "theme": "philosophy",
        "description": "Dark blue contemplative background"
    },
    {
        "name": "success_1.mp4",
        "color": "green",
        "theme": "success",
        "description": "Green prosperity background"
    },
    {
        "name": "inspiration_1.mp4",
        "color": "purple",
        "theme": "inspiration",
        "description": "Purple inspirational background"
    },
]

for video in videos:
    filepath = Path(f"data/raw/videos/{video['name']}")

    if filepath.exists():
        print(f"  ✓ {video['name']} already exists")
        continue

    # Generate 10-second video with FFmpeg
    # Create a simple color background video
    cmd = [
        'ffmpeg', '-f', 'lavfi', '-i',
        f"color={video['color']}:s=1080x1920:d=10",
        '-pix_fmt', 'yuv420p',
        str(filepath),
        '-y',
        '-loglevel', 'quiet'
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"  ✓ Generated {video['name']} ({video['description']})")
    except Exception as e:
        print(f"  ✗ Failed to generate {video['name']}: {e}")

# ============================================================================
# 2. GENERATE TEST MUSIC (10 seconds each, different tempos)
# ============================================================================
print("\n🎵 Generating test music files...")

music_tracks = [
    {
        "name": "pump_it_up.wav",
        "frequency": 440,
        "tempo": "fast",
        "description": "Fast-paced pump track"
    },
    {
        "name": "chill_vibes.wav",
        "frequency": 220,
        "tempo": "slow",
        "description": "Chill ambient track"
    },
    {
        "name": "epic_drop.wav",
        "frequency": 330,
        "tempo": "medium",
        "description": "Epic medium-tempo track"
    },
    {
        "name": "deep_bass.wav",
        "frequency": 55,
        "tempo": "fast",
        "description": "Deep bass track"
    },
    {
        "name": "uplifting.wav",
        "frequency": 660,
        "tempo": "fast",
        "description": "Uplifting high-energy track"
    },
]

for track in music_tracks:
    filepath = Path(f"data/raw/music/{track['name']}")

    if filepath.exists():
        print(f"  ✓ {track['name']} already exists")
        continue

    # Generate sine wave audio with FFmpeg
    cmd = [
        'ffmpeg', '-f', 'lavfi', '-i',
        f"sine=f={track['frequency']}:d=10",
        '-q:a', '9',
        '-acodec', 'libmp3lame',
        str(filepath),
        '-y',
        '-loglevel', 'quiet'
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"  ✓ Generated {track['name']} ({track['description']})")
    except Exception as e:
        print(f"  ✗ Failed to generate {track['name']}: {e}")

# ============================================================================
# 3. CREATE QUOTES FILE
# ============================================================================
print("\n💭 Creating quotes file...")

quotes_file = Path("data/raw/quotes.jsonl")

if quotes_file.exists():
    print(f"  ✓ quotes.jsonl already exists")
else:
    quotes = [
        # Motivation
        {"text": "The only way to do great work is to love what you do.", "author": "Steve Jobs", "category": "motivation", "theme": "motivation"},
        {"text": "Success is not final, failure is not fatal.", "author": "Winston Churchill", "category": "motivation", "theme": "motivation"},
        {"text": "Believe you can and you're halfway there.", "author": "Theodore Roosevelt", "category": "motivation", "theme": "motivation"},
        {"text": "Don't watch the clock; do what it does. Keep going.", "author": "Sam Levenson", "category": "motivation", "theme": "motivation"},

        # Hustle
        {"text": "The grind never stops. Success is a journey, not a destination.", "author": "Unknown", "category": "hustle", "theme": "hustle"},
        {"text": "Wake up with determination. Go to bed with satisfaction.", "author": "Unknown", "category": "hustle", "theme": "hustle"},
        {"text": "Your limitation only exists in your mind.", "author": "Unknown", "category": "hustle", "theme": "hustle"},
        {"text": "Hustle in silence. Let success make the noise.", "author": "Unknown", "category": "hustle", "theme": "hustle"},

        # Philosophy
        {"text": "The only true wisdom is knowing you know nothing.", "author": "Socrates", "category": "philosophy", "theme": "philosophy"},
        {"text": "Life is what happens when you're busy making other plans.", "author": "John Lennon", "category": "philosophy", "theme": "philosophy"},
        {"text": "To be or not to be, that is the question.", "author": "Shakespeare", "category": "philosophy", "theme": "philosophy"},
        {"text": "We are what we repeatedly do. Excellence, then, is not an act, but a habit.", "author": "Aristotle", "category": "philosophy", "theme": "philosophy"},

        # Success
        {"text": "Success is walking from failure to failure with no loss of enthusiasm.", "author": "Winston Churchill", "category": "success", "theme": "success"},
        {"text": "The secret of success is to do the common thing uncommonly well.", "author": "Unknown", "category": "success", "theme": "success"},
        {"text": "Success usually comes to those who are too busy to be looking for it.", "author": "Henry David Thoreau", "category": "success", "theme": "success"},

        # Inspiration
        {"text": "You are capable of amazing things.", "author": "Unknown", "category": "inspiration", "theme": "inspiration"},
        {"text": "Your potential is endless. Your will to succeed has to be stronger than your fear of failure.", "author": "Unknown", "category": "inspiration", "theme": "inspiration"},
        {"text": "Every expert was once a beginner.", "author": "Unknown", "category": "inspiration", "theme": "inspiration"},
        {"text": "The future belongs to those who believe in the beauty of their dreams.", "author": "Eleanor Roosevelt", "category": "inspiration", "theme": "inspiration"},
        {"text": "Believe in yourself. You are braver than you believe, stronger than you seem, smarter than you think.", "author": "A.A. Milne", "category": "inspiration", "theme": "inspiration"},
    ]

    try:
        with open(quotes_file, 'w') as f:
            for quote in quotes:
                f.write(json.dumps(quote) + '\n')
        print(f"  ✓ Created quotes.jsonl with {len(quotes)} quotes")
    except Exception as e:
        print(f"  ✗ Failed to create quotes.jsonl: {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "="*60)
print("✅ Test Assets Generated Successfully!")
print("="*60)

# Count created files
video_count = len(list(Path("data/raw/videos").glob("*.mp4")))
music_count = len(list(Path("data/raw/music").glob("*")))
quotes_count = 0
if quotes_file.exists():
    with open(quotes_file) as f:
        quotes_count = len(f.readlines())

print(f"\n📊 Assets Summary:")
print(f"  • Videos: {video_count} files")
print(f"  • Music: {music_count} files")
print(f"  • Quotes: {quotes_count} entries")

print(f"\n📁 Files created:")
print(f"  • data/raw/videos/ - {video_count} test videos")
print(f"  • data/raw/music/ - {music_count} test audio tracks")
print(f"  • data/raw/quotes.jsonl - {quotes_count} motivational quotes")

print(f"\n🚀 Ready to generate content!")
print(f"\nNext steps:")
print(f"  1. Start the bot: python main.py")
print(f"  2. In Telegram, send: /generate 3")
print(f"  3. Bot will create test reels using these assets")

print("\n" + "="*60)
