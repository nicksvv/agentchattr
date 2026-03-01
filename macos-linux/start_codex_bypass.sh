#!/usr/bin/env bash
# agentchattr — starts server (if not running) + Codex wrapper (auto-approve mode)
cd "$(dirname "$0")/.."

# Auto-create venv and install deps on first run
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt > /dev/null 2>&1
fi
source .venv/bin/activate

# Start server in a separate terminal if not already running
if ! lsof -i :8300 -sTCP:LISTEN >/dev/null 2>&1 && \
   ! ss -tlnp 2>/dev/null | grep -q ':8300 '; then
    if [[ "$OSTYPE" == darwin* ]]; then
        osascript -e "tell app \"Terminal\" to do script \"cd '$(pwd)' && source .venv/bin/activate && python run.py\"" > /dev/null 2>&1
    else
        if command -v gnome-terminal > /dev/null 2>&1; then
            gnome-terminal -- bash -c "cd '$(pwd)' && source .venv/bin/activate && python run.py; read"
        elif command -v xterm > /dev/null 2>&1; then
            xterm -e "cd '$(pwd)' && source .venv/bin/activate && python run.py" &
        else
            python run.py > data/server.log 2>&1 &
        fi
    fi
    # Wait for server to be ready (up to 15s)
    for i in $(seq 1 30); do
        (lsof -i :8300 -sTCP:LISTEN >/dev/null 2>&1 || ss -tlnp 2>/dev/null | grep -q ':8300 ') && break
        sleep 0.5
    done
fi

python wrapper.py codex -- --dangerously-bypass-approvals-and-sandbox
