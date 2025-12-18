#!/bin/bash

#############################################################################
#
# ShitPostBot - Quick Start Script
#
# This script starts the ShitPostBot with automatic setup checks
# It verifies dependencies, credentials, and system health before launch
#
# Usage:
#   ./start_bot.sh
#
#############################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
    exit 1
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_step() {
    echo -e "${CYAN}→ $1${NC}"
}

# Start startup sequence
print_header "ShitPostBot Startup"

# Check if venv exists
print_step "Checking virtual environment..."
if [ ! -d "venv" ]; then
    print_warning "Virtual environment not found"
    print_error "Please run: ./install.sh"
fi
print_success "Virtual environment found"

# Activate venv
print_step "Activating virtual environment..."
source venv/bin/activate
print_success "Virtual environment activated"

# Check if requirements installed
print_step "Checking dependencies..."
if ! python3 -c "import sqlalchemy" 2>/dev/null; then
    print_warning "Dependencies not installed"
    print_step "Installing dependencies..."
    pip install -r requirements.txt --quiet
    print_success "Dependencies installed"
else
    print_success "All dependencies found"
fi

# Check if .env exists
print_step "Checking credentials..."
if [ ! -f ".env" ]; then
    print_warning ".env file not found"
    print_step "Creating .env from template..."
    cp .env.example .env
    print_warning "Please edit .env and add your credentials"
    print_info "  nano .env"
    print_error "Credentials required - exiting"
fi

# Check if credentials are configured
if ! grep -q "TELEGRAM_BOT_TOKEN" .env || grep -q "TELEGRAM_BOT_TOKEN=your_" .env; then
    print_warning "Credentials not configured"
    print_info "Running setup wizard..."
    python3 setup_credentials.py

    if [ $? -ne 0 ]; then
        print_error "Setup cancelled"
        exit 1
    fi
else
    print_success "Credentials configured"
fi

# Run validation
print_header "Running Pre-Flight Checks"
if python3 validate_deployment.py 2>&1 | tail -1 | grep -q "ALL CHECKS PASSED"; then
    print_success "All checks passed!"
else
    print_warning "Some checks failed - review above"
fi

# Start the bot
print_header "Starting ShitPostBot"
echo ""
print_success "Bot is running! Control via Telegram:"
echo ""
echo -e "${CYAN}Commands:${NC}"
echo "  /start      - Initialize bot"
echo "  /status     - System status"
echo "  /generate N - Generate N reels"
echo "  /queue      - View pending reels"
echo "  /schedule   - View scheduled posts"
echo "  /preview ID - Preview reel by ID"
echo "  /analytics  - Performance report"
echo "  /help       - All commands"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

python3 main.py
