#!/bin/bash

# ANSI Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}⚡ Starting AutoTQ Production Station...${NC}"

# Check for Python 3
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}❌ Python not found! Please install Python 3.8+.${NC}"
    exit 1
fi

# Check version (simple check for 3.x)
VER=$($PYTHON_CMD -V 2>&1 | grep "Python 3")
if [ -z "$VER" ]; then
    echo -e "${YELLOW}⚠️  Warning: $PYTHON_CMD might not be Python 3. Please ensure you are using Python 3.${NC}"
fi

# Install Dependencies
echo -e "📦 Checking dependencies..."
$PYTHON_CMD -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to install dependencies.${NC}"
    read -p "Press Enter to exit..."
    exit 1
fi

echo -e "${GREEN}✅ Dependencies verified.${NC}"

# Run Script
echo -e "${GREEN}🚀 Launching Production Station...${NC}"
$PYTHON_CMD autotq_auto_production.py "$@"

