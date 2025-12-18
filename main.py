#!/usr/bin/env python3
"""
ShitPostBot Main Entry Point

Autonomous Instagram content generation and publishing bot.
Controlled via Telegram, powered by AI and smart content selection.

Usage:
    python3 main.py                 # Start with Telegram bot
    python3 main.py --generate 10   # Generate 10 reels manually
    python3 main.py --analytics     # Show analytics report
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Load environment variables first, before anything else
from dotenv import load_dotenv
load_dotenv()

from src.database import init_db, get_session
from src.controllers import TelegramBot, BotOrchestrator
from src.analytics import PerformanceAnalyzer
from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance

logger = get_logger(__name__)


def setup_database():
    """Initialize database."""
    logger.info("Setting up database...")
    try:
        engine = init_db()
        logger.info("✅ Database ready")
        return engine
    except Exception as e:
        logger.error(f"❌ Database setup failed: {e}")
        sys.exit(1)


async def run_bot():
    """Run Telegram bot with orchestrator."""
    logger.info("Starting ShitPostBot...")

    # Setup
    setup_database()

    # Create instances
    telegram_bot = TelegramBot()
    orchestrator = BotOrchestrator(telegram_bot=telegram_bot)
    telegram_bot.orchestrator = orchestrator

    # Start
    logger.info("🚀 Starting bot...")
    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        await orchestrator.stop()


async def generate_content(count: int):
    """Generate content manually."""
    logger.info(f"Generating {count} reels...")

    setup_database()

    orchestrator = BotOrchestrator()
    await orchestrator.start()
    results = await orchestrator.generate_content(count=count)

    print(f"\n✅ Generated {len(results)} reels:")
    for result in results:
        print(f"  • Reel #{result['id']}: {result['output_path']}")

    await orchestrator.stop()


async def show_analytics(days: int):
    """Show analytics report."""
    logger.info(f"Showing analytics for last {days} days...")

    setup_database()

    session = get_session()
    analyzer = PerformanceAnalyzer(session)

    report = analyzer.get_summary_report(days=days)
    print(f"\n{report}")

    session.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="ShitPostBot - Autonomous Instagram content generation"
    )

    parser.add_argument(
        "--generate",
        type=int,
        metavar="COUNT",
        help="Generate N reels and exit"
    )

    parser.add_argument(
        "--analytics",
        action="store_true",
        help="Show analytics report for last 7 days"
    )

    parser.add_argument(
        "--analytics-days",
        type=int,
        default=7,
        metavar="DAYS",
        help="Days to include in analytics (default: 7)"
    )

    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit"
    )

    args = parser.parse_args()

    # Check version
    if args.version:
        print("ShitPostBot v1.0")
        print("Autonomous Instagram Content Generation & Publishing")
        sys.exit(0)

    # Verify configuration
    try:
        config = get_config_instance()
        logger.info(f"Configuration loaded: {config.get('llm.provider')} LLM, "
                   f"Instagram API v{config.get('instagram.api_version')}")
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    try:
        # Run requested operation
        if args.generate:
            asyncio.run(generate_content(args.generate))
        elif args.analytics:
            asyncio.run(show_analytics(args.analytics_days))
        else:
            # Default: run bot - use manual loop to avoid asyncio.run() closing issues
            import sys
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                loop.run_until_complete(run_bot())
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
            finally:
                # Don't close the loop - let it finish properly
                pass

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
