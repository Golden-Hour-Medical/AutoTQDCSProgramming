#!/bin/bash
# AutoTQ Programming Tools - Linux/Mac Setup and Program Script
# This script downloads the latest files and then programs devices

set -e  # Exit on any error

echo "=========================================="
echo "  AutoTQ Programming Tools for Unix"
echo "=========================================="
echo

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found"
    echo "Please install Python 3.8+ using your package manager"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "CentOS/RHEL: sudo yum install python3 python3-pip"
    echo "macOS: brew install python3"
    exit 1
fi

# Check Python version
python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" || {
    echo "ERROR: Python 3.8+ required"
    python3 --version
    exit 1
}

echo "Step 1: Installing required packages..."
python3 -m pip install --user --upgrade pip
python3 -m pip install --user -r requirements.txt || {
    echo "ERROR: Failed to install packages"
    echo "On Linux, you may need to add ~/.local/bin to your PATH"
    echo "Or install system-wide with: sudo python3 -m pip install -r requirements.txt"
    exit 1
}

echo
echo "Step 2: Downloading latest firmware and audio files..."
python3 autotq_setup.py || {
    echo "ERROR: Setup failed"
    echo "Check your internet connection and credentials"
    exit 1
}

echo
echo "Step 3: Programming device(s) with optimized settings..."
python3 autotq_programmer.py || {
    echo "ERROR: Programming failed"
    echo "Check device connection and permissions"
    echo "On Linux, ensure user is in dialout group:"
    echo "  sudo usermod -a -G dialout \$USER"
    echo "Then logout and login again"
    exit 1
}

echo
echo "=========================================="
echo "  SUCCESS! Device programming completed"
echo "  Production mode optimizations used"
echo "=========================================="
echo 