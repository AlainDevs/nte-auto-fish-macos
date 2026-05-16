#!/usr/bin/env bash
set -euo pipefail

APP_NAME="NTE Auto Fisher"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}.dmg"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

"${PYTHON_BIN}" -m PyInstaller --clean --noconfirm nte_fisher.spec

if ! command -v create-dmg >/dev/null 2>&1; then
  cat <<'EOF'
PyInstaller created the .app bundle, but create-dmg is not installed.
Install it with: brew install create-dmg
Then re-run: scripts/build_dmg.sh
EOF
  exit 0
fi

rm -f "${DMG_PATH}"
create-dmg \
  --volname "${APP_NAME}" \
  --window-pos 200 120 \
  --window-size 640 420 \
  --icon-size 128 \
  --icon "${APP_NAME}.app" 180 170 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 460 170 \
  "${DMG_PATH}" \
  "${APP_PATH}"

echo "Built ${APP_PATH}"
echo "Built ${DMG_PATH}"
