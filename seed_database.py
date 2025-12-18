#!/usr/bin/env python3
"""
Seed the database with test assets (videos, music, quotes).
This makes the test files discoverable to the bot.
"""

import json
from pathlib import Path
from src.database import init_db, get_session
from src.database.repositories import VideoRepository, MusicRepository, QuoteRepository

print("🌱 Seeding Database with Test Assets...\n")

# Initialize database
try:
    init_db()
    print("✓ Database initialized")
except Exception as e:
    print(f"✓ Database already initialized: {e}")

session = get_session()

# ============================================================================
# 1. LOAD VIDEOS
# ============================================================================
print("\n📹 Loading videos...")
video_repo = VideoRepository(session)
video_dir = Path("data/raw/videos")

if video_dir.exists():
    existing_videos = {v.filename for v in video_repo.get_all()}

    for video_file in sorted(video_dir.glob("*.mp4")):
        if video_file.name in existing_videos:
            print(f"  ✓ {video_file.name} already in database")
            continue

        # Determine theme from filename
        theme = "motivation"
        if "hustle" in video_file.name:
            theme = "hustle"
        elif "philosophy" in video_file.name:
            theme = "philosophy"
        elif "success" in video_file.name:
            theme = "success"
        elif "inspiration" in video_file.name:
            theme = "inspiration"

        try:
            video = video_repo.create(
                filename=video_file.name,
                source="test_generated",
                duration=10.0,
                resolution="1080x1920",
                theme=theme,
                quality_score=0.8,
                usage_count=0
            )
            print(f"  ✓ Added {video_file.name} (theme: {theme})")
        except Exception as e:
            print(f"  ✗ Failed to add {video_file.name}: {e}")

# ============================================================================
# 2. LOAD MUSIC
# ============================================================================
print("\n🎵 Loading music...")
music_repo = MusicRepository(session)
music_dir = Path("data/raw/music")

if music_dir.exists():
    existing_music = {m.filename for m in music_repo.get_all()}

    for music_file in sorted(music_dir.glob("*")):
        if music_file.name in existing_music:
            print(f"  ✓ {music_file.name} already in database")
            continue

        # Determine energy level from filename
        energy = "medium"
        if "pump" in music_file.name or "uplifting" in music_file.name:
            energy = "high"
        elif "chill" in music_file.name:
            energy = "low"

        bass_score = 0.15 if "bass" in music_file.name else 0.10

        try:
            music = music_repo.create(
                filename=music_file.name,
                source="test_generated",
                duration=10.0,
                bpm=120,
                energy_level=energy,
                bass_score=bass_score,
                tags=f"{energy},test",
                usage_count=0
            )
            print(f"  ✓ Added {music_file.name} (energy: {energy})")
        except Exception as e:
            print(f"  ✗ Failed to add {music_file.name}: {e}")

# ============================================================================
# 3. LOAD QUOTES
# ============================================================================
print("\n💭 Loading quotes...")
quote_repo = QuoteRepository(session)
quotes_file = Path("data/raw/quotes.jsonl")

if quotes_file.exists():
    existing_quotes = {q.text for q in quote_repo.get_all()}
    added = 0

    with open(quotes_file) as f:
        for line in f:
            try:
                quote_data = json.loads(line.strip())

                if quote_data["text"] in existing_quotes:
                    continue

                quote = quote_repo.create(
                    text=quote_data["text"],
                    author=quote_data.get("author", "Unknown"),
                    category=quote_data.get("category", "general"),
                    usage_count=0
                )
                added += 1
            except Exception as e:
                print(f"  ✗ Failed to add quote: {e}")

    if added > 0:
        print(f"  ✓ Added {added} new quotes to database")
    else:
        print(f"  ✓ All quotes already in database")

# ============================================================================
# SUMMARY
# ============================================================================
session.close()

print("\n" + "="*60)
print("✅ Database Seeded Successfully!")
print("="*60)

# Get counts
session = get_session()
video_count = len(video_repo.get_all())
music_count = len(music_repo.get_all())
quote_count = len(quote_repo.get_all())
session.close()

print(f"\n📊 Database Contents:")
print(f"  • Videos: {video_count}")
print(f"  • Music: {music_count}")
print(f"  • Quotes: {quote_count}")

print(f"\n🚀 Ready to generate content!")
print(f"\nNext steps:")
print(f"  1. Start the bot: python main.py")
print(f"  2. In Telegram, send: /generate 3")
print(f"  3. Bot will create reels from these assets")
print(f"  4. Check /queue to see generated reels")

print("\n" + "="*60)
