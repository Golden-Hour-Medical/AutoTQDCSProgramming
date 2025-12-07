#!/bin/bash

# ANSI Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

echo -e "${CYAN}===================================================${NC}"
echo -e "${CYAN}⚡ Starting AutoTQ Production Station${NC}"
echo -e "${CYAN}===================================================${NC}"

# ----------------------------------------------------
# 1. DETECT PYTHON (Robust Method)
# ----------------------------------------------------
PYTHON_CMD=""

# A) Check for Virtual Environment
if [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
    echo -e "${GRAY}[INFO] Using virtual environment: $PYTHON_CMD${NC}"
# B) Check for python3
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
    echo -e "${GRAY}[INFO] Found python3 in PATH${NC}"
# C) Check for specific versions if python3 alias missing
elif command -v python3.11 &>/dev/null; then
    PYTHON_CMD="python3.11"
    echo -e "${GRAY}[INFO] Found python3.11${NC}"
elif command -v python3.10 &>/dev/null; then
    PYTHON_CMD="python3.10"
    echo -e "${GRAY}[INFO] Found python3.10${NC}"
# D) Fallback to python
elif command -v python &>/dev/null; then
    # Verify it is Python 3
    VER=$(python -V 2>&1)
    if [[ $VER == *"Python 3"* ]]; then
        PYTHON_CMD="python"
        echo -e "${GRAY}[INFO] Found python (Python 3)${NC}"
    else
        echo -e "${YELLOW}⚠️  Found 'python' but it appears to be Python 2 ($VER). Skipping.${NC}"
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ Python 3 not found!${NC}"
    echo "Please install Python 3.8+ using your package manager."
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "MacOS: brew install python"
    read -p "Press Enter to exit..."
    exit 1
fi

# ----------------------------------------------------
# 2. INSTALL DEPENDENCIES
# ----------------------------------------------------
echo -e "\n${CYAN}📦 Checking dependencies...${NC}"
$PYTHON_CMD -m pip install -r requirements.txt > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to install dependencies!${NC}"
    echo -e "Trying to install explicitly..."
    $PYTHON_CMD -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        read -p "Press Enter to exit..."
        exit 1
    fi
fi
echo -e "${GREEN}✅ Dependencies verified.${NC}"

# ----------------------------------------------------
# 3. RUN SCRIPT
# ----------------------------------------------------
echo -e "\n${GREEN}🚀 Launching Production Station...${NC}"
echo -e "${GRAY}---------------------------------------------------${NC}"

$PYTHON_CMD autotq_auto_production.py "$@"
