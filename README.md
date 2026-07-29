# ShitPostBot 🤖

**Autonomous Instagram Content Generation & Publishing Bot**

Transform your Instagram strategy with AI-powered content generation, smart scheduling, and performance analytics - all controlled via Telegram.

## ✨ Features

### Phase 1 & 2: Foundation (✅ Complete)
- ✅ **SQLite Database** - Persistent storage with 9 tables
- ✅ **Smart Content Selection** - Weighted algorithm favoring fresh, unused content
- ✅ **Theme Matching** - 3 configurable themes (motivation, philosophy, hustle)
- ✅ **Configuration System** - YAML-based with environment variable support
- ✅ **Repository Pattern** - Clean data access layer
- ✅ **Data Migration** - Import legacy ledger.jsonl and uploaded.jsonl

### Phase 3: Video Pipeline (✅ Rewritten)
- ✅ **Remotion-based rendering** (`renderer/`) - replaces the old raw-ffmpeg
  filter-graph composition; see `renderer/README.md`
- ✅ **ElevenLabs voiceover** - drives reel duration from real word-level
  timestamps instead of a fixed 13s
- ✅ **Footage QC decision tree** (`src/processors/footage_qc.py`) - every
  downloaded clip is scored (relevance/aesthetic/crop-fit/safety) before use
- ✅ **AI beat-sheet scripts** (`src/services/gemini_content_generator.py`) -
  hook/body/payoff generation, replacing the flat single-quote prompt
- 🔜 **S3 Storage** - Cloud hosting with presigned URLs

### Phase 4: Coming Soon
- 🔜 **Telegram Bot** - `/generate`, `/approve`, `/analytics` commands
- 🔜 **Background Automation** - Auto-generate and schedule posts
- 🔜 **Content Calendar** - Weekly schedule with themes
- 🔜 **Approval Workflow** - Generate → Preview → Approve → Post

### Phase 5: Coming Soon
- 🔜 **Performance Analytics** - Engagement tracking and analysis
- 🔜 **Self-Learning** - Optimize based on what works
- 🔜 **Time Optimization** - Post at best times for your audience

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- FFmpeg (for video generation)
- Instagram Business Account with access token
- OpenAI API key (for captions)
- Telegram Bot token

### Installation

```bash
# Clone/setup
cd shitPostBot1

# Install dependencies
pip install -r requirements.txt

# Initialize database
python3 -c "from src.database import init_db; init_db()"

# (Optional) Migrate existing data
python3 migrate_legacy_data.py

# Configure
cp .env.example .env  # Edit with your credentials
# Edit config/config.yaml as needed
```

### First Run

```bash
# Test database connection
python3 << 'EOF'
from src.database import get_session
from src.database.repositories import VideoRepository

session = get_session()
video_repo = VideoRepository(session)
print(f"Videos in database: {len(video_repo.get_all())}")
print("✅ System ready!")
EOF
```

---

## 📚 Documentation

- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Detailed installation & configuration
- **[PHASE1_COMPLETE.md](PHASE1_COMPLETE.md)** - Technical deep dive
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - Feature checklist & roadmap

---

## 🏗️ Architecture

### Core Components

#### Database Layer
```
models.py          → SQLAlchemy ORM (9 tables)
repositories.py    → Data access layer with 9 repositories
__init__.py        → Database initialization & session management
```

#### Content Processing
```
content_selector.py → Intelligent asset selection with weighted algorithm
(Phase 3)
video_generator.py  → FFmpeg video composition
llm_provider.py     → OpenAI/Anthropic caption generation
```

#### External Integrations
```
instagram.py       → Instagram Graph API wrapper
storage.py         → S3 upload and presigned URLs
content_sources.py → Pexels, Pixabay, Freesound APIs
```

#### Orchestration
```
orchestrator.py    → Main coordinator (Phase 4)
telegram_bot.py    → Telegram command handler (Phase 4)
```

#### Analytics
```
performance_analyzer.py → Engagement analysis (Phase 5)
metrics_collector.py    → Instagram metrics polling (Phase 5)
```

---

## 📊 Database Schema

### Main Tables

**Video** - Stock footage clips
- filename, source, duration, resolution
- tags, theme, usage_count, quality_score
- created_at, last_used_at

**Music** - Audio tracks
- filename, source, duration, bpm
- bass_score, energy_level, tags, usage_count
- created_at, last_used_at

**Quote** - Motivational quotes
- text, author, category, length
- usage_count, created_at, last_used_at

**GeneratedReel** - Generated videos awaiting approval
- video_id, music_id, quote_id (foreign keys)
- output_path, caption, duration
- status (pending/approved/rejected/published)
- quality_score, render_time, file_size
- created_at, approved_at

**ScheduledPost** - Posts scheduled for publishing
- reel_id, scheduled_time, status
- retry_count, error_message, published_at

**PublishedPost** - Successfully published posts
- reel_id, instagram_media_id, caption
- published_at

**PostMetrics** - Engagement tracking
- post_id, likes, comments, shares, reach, saves
- engagement_rate, collected_at

**ContentCalendar** - Weekly schedule
- date, time_slot, theme, status
- reel_id, scheduled_post_id

---

## 🧠 Smart Content Selection

### Algorithm

The system uses **weighted random selection** to balance novelty and variety:

```
weight = (1 / (1 + usage_count)) × recency_factor

where:
  1 + usage_count        → Penalizes frequently used assets
  recency_factor = 1.0   → Never used or last used > 7 days
  recency_factor = 0.2   → Last used within 7 days
```

### Themes

Three pre-configured themes ensure content coherence:

| Theme | Videos | Music | Quotes |
|-------|--------|-------|--------|
| **Motivation** | Gym, workout, business | High energy | Success, achievement |
| **Philosophy** | City, night, nature | Medium energy | Wisdom, meaning |
| **Hustle** | Boxing, training, business | High energy | Work, grind, succeed |

### Selection Process

```python
from src.processors.content_selector import ContentSelector

# Initialize
selector = ContentSelector(session, config)

# Select themed combination
combo = selector.get_themed_combination("motivation")
# combo.video, combo.music, combo.quote, combo.theme

# Update tracking
selector.update_usage_counts(combo)
```

---

## ⚙️ Configuration

### config/config.yaml

```yaml
instagram:
  user_id: ${IG_USER_ID}
  access_token: ${IG_ACCESS_TOKEN}

telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  admin_users: [123456789]

llm:
  provider: "openai"
  model: "gpt-4o-mini"

scheduling:
  post_times:
    - day: 1   # Monday
      time: "18:00"
    - day: 3   # Wednesday
      time: "18:00"
    - day: 5   # Friday
      time: "18:00"
  timezone: "Europe/Istanbul"
```

---

## 🎯 Workflow

### Current (Phase 1-2)
1. ✅ Database and selection system ready
2. ✅ Configuration system functional
3. ✅ Can select smart content combinations

### Coming Soon (Phase 3-5)
1. 🔄 Generate videos from selected content
2. 🔄 Generate captions with AI
3. 🔜 Send preview to Telegram for approval
4. 🔜 User approves via bot
5. 🔜 Post automatically at scheduled time
6. 🔜 Collect engagement metrics
7. 🔜 Optimize selection based on performance

---

## 🛠️ Development

### Project Structure
```
shitPostBot1/
├── src/
│   ├── agents/          # Multi-agent system (Phase 4)
│   ├── controllers/     # Orchestration (Phase 4)
│   ├── services/        # External APIs (Phase 3)
│   ├── processors/      # Content processing
│   ├── database/        # ORM & data access
│   ├── analytics/       # Performance analysis (Phase 5)
│   └── utils/           # Shared utilities
├── config/config.yaml   # Configuration
├── data/                # Assets and outputs
├── database/bot.db      # SQLite database (auto-created)
├── logs/                # Application logs
└── requirements.txt     # Dependencies
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run tests
pytest tests/ -v --cov=src

# Or specific test
pytest tests/unit/test_content_selector.py -v
```

### Code Quality

```bash
# Format code
black src/ --line-length=100

# Lint
flake8 src/ --max-line-length=100

# Sort imports
isort src/
```

---

## 📈 Performance

- **Database:** SQLite with WAL mode for concurrent reads
- **Selection:** O(n) weighted random, ~100ms for 50 assets
- **Video Generation:** ~2-5 minutes per reel (FFmpeg dependent)
- **API Calls:** Batched with rate limiting

---

## 🔒 Security

✅ Credentials stored in .env (not in config.yaml)
✅ Database transactions for ACID compliance
✅ SQL injection protection (SQLAlchemy ORM)
✅ Rate limiting for API calls
✅ Error messages don't leak sensitive data
✅ Admin-only Telegram commands

---

## 🐛 Troubleshooting

### Database Error
```bash
rm database/bot.db
python3 -c "from src.database import init_db; init_db()"
```

### Import Error
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python3 main.py
```

### Configuration Not Loading
```bash
python3 -c "from src.utils.config_loader import get_config; print(get_config())"
```

---

## 📞 Support

See documentation files for detailed help:
- Setup issues → SETUP_GUIDE.md
- Architecture questions → PHASE1_COMPLETE.md
- Status & roadmap → IMPLEMENTATION_STATUS.md

---

## 📝 License

MIT License - Feel free to use for personal/commercial projects

---

## 🚀 Roadmap

### Phase 3: Services (Next)
- [ ] Refactor uploadToInstagram.py → services/instagram.py
- [ ] Refactor generateVideo.py → processors/video_generator.py
- [ ] Create services/llm_provider.py
- [ ] Test with real Instagram account

### Phase 4: Telegram & Automation
- [ ] Implement Telegram bot with commands
- [ ] Create orchestrator for background jobs
- [ ] Setup APScheduler for automation
- [ ] Implement approval workflow

### Phase 5: Analytics
- [ ] Collect Instagram metrics
- [ ] Build performance analyzer
- [ ] Create insights engine
- [ ] Optimize selection weights

---

**Status: Phase 1 & 2 Complete - Ready for Phase 3 🚀**

Currently have:
- ✅ Database with 9 tables
- ✅ Repository pattern data access
- ✅ Smart weighted selection algorithm
- ✅ Theme matching system
- ✅ Configuration management
- ✅ Logging setup
- ✅ Data migration from legacy

Next: Refactor existing scripts into services and integrate LLM for captions
