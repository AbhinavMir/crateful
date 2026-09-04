#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT=7531
NO_SERVICE=0
[ "${1:-}" = "--no-service" ] && NO_SERVICE=1

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
fail() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

say "1/4 Checking requirements"
command -v python3 >/dev/null || fail "python3 not found. Install Python 3.10 or newer."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required. Found: $(python3 --version)"
ok "$(python3 --version)"
if command -v ffmpeg >/dev/null; then
  ok "ffmpeg"
else
  case "$(uname -s)" in
    Darwin) fail "ffmpeg not found. Run: brew install ffmpeg" ;;
    *)      fail "ffmpeg not found. Debian/Ubuntu: sudo apt install ffmpeg" ;;
  esac
fi
command -v git >/dev/null && ok "git" || echo "  ! git not found. The in-app updater needs it."

say "2/4 Preparing helper/.venv"
"$ROOT/helper/run.sh" --setup-only
ok "dependencies installed"

say "3/4 Starting the helper"
if [ "$(uname -s)" = "Darwin" ] && [ "$NO_SERVICE" = 0 ]; then
  "$ROOT/helper/service.sh" install >/dev/null
  ok "LaunchAgent installed (starts at login, restarts on crash)"
else
  echo "  Start it with: $ROOT/helper/run.sh"
  echo "  On macOS you can install the background service later: helper/service.sh install"
fi

up=0
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/status" >/dev/null 2>&1; then up=1; break; fi
  sleep 0.5
done
if [ "$up" = 1 ]; then
  ok "helper answers on http://127.0.0.1:$PORT"
else
  echo "  ! helper is not answering yet. Check: helper/service.sh status"
fi

say "4/4 Load the extension in Chrome"
cat <<STEPS
  1. Open chrome://extensions
  2. Turn on "Developer mode" (top right)
  3. Click "Load unpacked" and pick:
       $ROOT/extension
  4. Click the Crateful icon, open Settings, and add your API key
     (Anthropic or OpenAI), or pick Ollama for a local model.

Library folders: ~/YTD_DJ (audio) and ~/YTD_DJ_Video (video). Change them in Settings.
STEPS
