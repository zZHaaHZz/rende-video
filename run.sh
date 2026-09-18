#!/bin/bash
# Chạy AI Video Creator
# Usage: ./run.sh         → chạy tool.py (bản gốc)
#        ./run.sh new     → chạy tool_new.py (bản refactored, bỏ tab Veo3)

cd "$(dirname "$0")"

source venv/bin/activate

if [ "$1" = "new" ]; then
    echo "▶ Chạy tool_new.py (refactored)..."
    streamlit run tool_new.py
else
    echo "▶ Chạy tool.py (bản gốc)..."
    streamlit run tool.py
fi
