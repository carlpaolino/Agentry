#!/bin/bash
# Double-click to open Frontdesk Builder (macOS). First run installs everything.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -f .env ]; then
  echo "Missing .env: copy .env.example to .env and fill in the four keys."; read -p "Press Enter to close"; exit 1
fi
streamlit run app.py
