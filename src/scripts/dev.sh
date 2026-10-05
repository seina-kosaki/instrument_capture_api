#!/usr/bin/env bash
# 開発用: API(:8000) と 静的アプリ(:8081) を起動する。Ctrl+C で両方停止。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && python -m uvicorn app.asgi:app --reload --port 8000) &
API_PID=$!
python -m http.server 8081 --directory "$ROOT/apps" &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null' EXIT
echo "撮影アプリ : http://localhost:8081/capture/index.html"
echo "タグ付けUI : http://localhost:8081/tagger/index.html"
echo "API docs   : http://localhost:8000/docs"
wait
