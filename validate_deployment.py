#!/usr/bin/env python3
"""
ShitPostBot - Pre-Deployment Validation

Validates that all systems are ready for deployment.
Run this before starting the bot in production.
"""

import sys
import os
from pathlib import Path

def print_header(text):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def check_directories():
    """Check that all required directories exist."""
    print_header("📁 Checking Directories")

    required_dirs = [
        "src",
        "src/database",
        "src/services",
        "src/processors",
        "src/controllers",
        "src/analytics",
        "src/utils",
        "config",
        "database",
        "data",
        "data/raw",
        "data/output",
    ]

    all_exist = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists() and path.is_dir():
            print(f"✅ {dir_path:40} exists")
        else:
            print(f"❌ {dir_path:40} MISSING")
            all_exist = False

    return all_exist


def check_files():
    """Check that all required files exist."""
    print_header("📄 Checking Configuration Files")

    required_files = [
        ("main.py", "Main entry point"),
        ("config/config.yaml", "Configuration"),
        (".env", "Environment variables"),
        ("requirements.txt", "Dependencies"),
        ("database/bot.db", "Database"),
        ("QUICKSTART.md", "Quick start guide"),
        ("DEPLOYMENT_GUIDE.md", "Deployment guide"),
    ]

    all_exist = True
    for file_path, description in required_files:
        path = Path(file_path)
        if path.exists():
            size = path.stat().st_size
            size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
            print(f"✅ {file_path:35} {size_str:>10}  ({description})")
        else:
            print(f"❌ {file_path:35} MISSING  ({description})")
            all_exist = False

    return all_exist


def check_env_vars():
    """Check that required environment variables are set."""
    print_header("🔐 Checking Environment Variables")

    # Load .env file
    from dotenv import load_dotenv
    load_dotenv()

    required_vars = [
        "IG_USER_ID",
        "IG_ACCESS_TOKEN",
        "IG_APP_ID",
        "IG_APP_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
    ]

    optional_vars = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_BUCKET_NAME",
        "AWS_REGION",
    ]

    missing_required = []
    missing_optional = []

    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Show first 10 chars only for security
            display = value[:10] + "..." if len(value) > 10 else value
            print(f"✅ {var:30} configured")
        else:
            print(f"❌ {var:30} NOT SET")
            missing_required.append(var)

    print()

    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var:30} configured")
        else:
            print(f"⚠️  {var:30} not set (optional)")
            missing_optional.append(var)

    return len(missing_required) == 0


def check_python_imports():
    """Check that all required Python packages are installed."""
    print_header("🐍 Checking Python Packages")

    required_packages = [
        ("sqlalchemy", "Database ORM"),
        ("telegram.ext", "Telegram Bot"),
        ("apscheduler", "Job Scheduler"),
        ("yaml", "YAML Config"),
        ("dotenv", "Environment loader"),
        ("openai", "OpenAI API"),
        ("ffmpeg", "FFmpeg Python"),
        ("boto3", "AWS S3"),
        ("requests", "HTTP Client"),
    ]

    all_available = True
    for package, description in required_packages:
        try:
            __import__(package)
            print(f"✅ {package:30} available  ({description})")
        except ImportError:
            print(f"❌ {package:30} NOT installed  ({description})")
            all_available = False

    return all_available


def check_config():
    """Check that config.yaml is properly formatted."""
    print_header("⚙️  Checking Configuration")

    try:
        import yaml
        from src.utils.config_loader import get_config_instance

        config = get_config_instance()

        # Check required sections
        sections = [
            ("instagram", "Instagram API"),
            ("telegram", "Telegram Bot"),
            ("llm", "Language Model"),
            ("content", "Content Generation"),
            ("scheduling", "Scheduling"),
            ("database", "Database"),
        ]

        all_sections_ok = True
        for section, description in sections:
            try:
                value = config.get(section)
                if value:
                    print(f"✅ {section:20} configured  ({description})")
                else:
                    print(f"❌ {section:20} empty  ({description})")
                    all_sections_ok = False
            except Exception as e:
                print(f"❌ {section:20} error: {e}")
                all_sections_ok = False

        return all_sections_ok

    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return False


def check_database():
    """Check that database is initialized."""
    print_header("💾 Checking Database")

    try:
        from src.database import get_session, init_db

        # Check if database file exists
        db_path = Path("database/bot.db")
        if db_path.exists():
            size = db_path.stat().st_size
            size_mb = size / (1024 * 1024)
            print(f"✅ Database file exists  ({size_mb:.2f} MB)")
        else:
            print(f"⚠️  Database file not found, initializing...")
            try:
                init_db()
                print(f"✅ Database initialized")
            except Exception as e:
                print(f"❌ Failed to initialize database: {e}")
                return False

        # Try to get a session
        try:
            session = get_session()
            session.close()
            print(f"✅ Database connection works")
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False

    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return False


def check_services():
    """Check that all services can be imported."""
    print_header("🔧 Checking Services")

    services = [
        ("src.services.instagram", "Instagram Service"),
        ("src.services.llm_provider", "LLM Provider"),
        ("src.processors.video_generator", "Video Generator"),
        ("src.processors.content_selector", "Content Selector"),
        ("src.controllers.telegram_bot", "Telegram Bot"),
        ("src.controllers.orchestrator", "Orchestrator"),
        ("src.analytics.performance_analyzer", "Performance Analyzer"),
    ]

    all_available = True
    for module, description in services:
        try:
            __import__(module)
            print(f"✅ {module:45} ({description})")
        except Exception as e:
            print(f"❌ {module:45} ERROR: {str(e)[:30]}")
            all_available = False

    return all_available


def check_content_directories():
    """Check that content directories have files."""
    print_header("📚 Checking Content Directories")

    data_dirs = [
        ("data/raw/videos", "Videos"),
        ("data/raw/music", "Music"),
        ("data/raw/quotes.jsonl", "Quotes"),
    ]

    for path, description in data_dirs:
        path_obj = Path(path)
        if path_obj.is_file():
            size = path_obj.stat().st_size
            lines = len(open(path_obj).readlines()) if path.endswith('.jsonl') else "N/A"
            print(f"✅ {path:35} exists  ({lines} records)")
        elif path_obj.is_dir():
            count = len(list(path_obj.glob("*")))
            print(f"⚠️  {path:35} ({count} files)")
        else:
            print(f"⚠️  {path:35} not found (optional)")


def main():
    """Run all validation checks."""
    print("\n" + "="*60)
    print("🤖 ShitPostBot - Pre-Deployment Validation")
    print("="*60)

    checks = [
        ("Directories", check_directories),
        ("Files", check_files),
        ("Environment Variables", check_env_vars),
        ("Python Packages", check_python_imports),
        ("Configuration", check_config),
        ("Database", check_database),
        ("Services", check_services),
        ("Content", check_content_directories),
    ]

    results = {}
    for name, check_func in checks:
        try:
            result = check_func()
            results[name] = result
        except Exception as e:
            print(f"\n❌ Error in {name} check: {e}")
            results[name] = False

    # Summary
    print_header("📊 Validation Summary")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:12} {name}")

    print(f"\nResult: {passed}/{total} checks passed")

    if passed == total:
        print("\n" + "="*60)
        print("✅ ALL CHECKS PASSED - READY FOR DEPLOYMENT!")
        print("="*60)
        print("\n🚀 To start the bot:")
        print("   source venv/bin/activate")
        print("   python3 main.py")
        print("\n📱 Control via Telegram:")
        print("   /start    - Get started")
        print("   /status   - Check status")
        print("   /help     - All commands")
        print("\n" + "="*60 + "\n")
        return 0
    else:
        print("\n" + "="*60)
        print(f"❌ {total - passed} check(s) failed")
        print("="*60)
        print("\n⚠️  Please fix the issues above before deploying")
        print("\nFor help, see DEPLOYMENT_GUIDE.md or QUICKSTART.md\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
