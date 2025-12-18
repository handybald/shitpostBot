#!/bin/bash

#############################################################################
#
# ShitPostBot - Installation & Setup Script
#
# This script sets up ShitPostBot for Linux/Mac systems
# It creates a Python virtual environment and installs all dependencies
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
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

# Start installation
print_header "ShitPostBot Installation"

# Check if Python 3 is installed
print_step "Checking Python 3..."
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 not found!"
    echo ""
    echo "Please install Python 3:"
    echo "  macOS: brew install python3"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-pip python3-venv"
    echo "  Fedora: sudo dnf install python3 python3-pip"
    exit 1
fi
print_success "Python found: $(python3 --version)"

# Check Python version (3.8+)
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
print_info "Python version: $PYTHON_VERSION"

# Check if FFmpeg is installed (optional but recommended)
print_step "Checking FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    print_success "FFmpeg found: $(ffmpeg -version | head -1)"
else
    print_warning "FFmpeg not found (optional but recommended for video processing)"
    echo "  Install: brew install ffmpeg (macOS) or sudo apt-get install ffmpeg (Linux)"
fi

# Create virtual environment
print_header "Setting Up Python Environment"
print_step "Creating virtual environment..."
if [ -d "venv" ]; then
    print_warning "Virtual environment already exists, skipping creation"
else
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
print_step "Activating virtual environment..."
source venv/bin/activate
print_success "Virtual environment activated"

# Upgrade pip
print_step "Upgrading pip..."
pip install --quiet --upgrade pip setuptools wheel
print_success "pip upgraded"

# Install dependencies
print_header "Installing Dependencies"
print_step "Installing Python packages..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    print_success "Dependencies installed"
else
    print_error "requirements.txt not found!"
fi

# Setup .env file
print_header "Configuring Credentials"
if [ ! -f ".env" ]; then
    print_step "Creating .env file..."
    cp .env.example .env 2>/dev/null || touch .env
    print_success ".env file created"
    print_warning "Please edit .env and add your credentials:"
    print_info "  nano .env"
else
    print_warning ".env file already exists, skipping"
fi

# Final instructions
print_header "Setup Complete!"
echo ""
print_success "ShitPostBot is ready to use!"
echo ""
echo "Next steps:"
echo ""
echo -e "${CYAN}1. Add your credentials${NC}"
echo "   Edit .env and fill in your tokens:"
echo "   • TELEGRAM_BOT_TOKEN (from @BotFather)"
echo "   • OPENAI_API_KEY (from platform.openai.com)"
echo "   • Instagram/Meta credentials (from Meta Developers)"
echo ""
echo -e "${CYAN}2. Run the setup wizard${NC}"
echo "   python3 setup_credentials.py"
echo ""
echo -e "${CYAN}3. Generate test assets (optional)${NC}"
echo "   python3 quick_setup.py"
echo ""
echo -e "${CYAN}4. Start the bot${NC}"
echo "   ./start_bot.sh"
echo ""
echo "For detailed instructions, see: START_HERE.md"
echo ""
