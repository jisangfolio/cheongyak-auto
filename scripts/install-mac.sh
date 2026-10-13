#!/bin/bash
# Mac 자동 실행 설치 (한 번만): 매일 09:07, 18:07 에 scripts/mac-run.sh
# 제거: launchctl bootout gui/$(id -u)/com.cheongyak.lh && rm ~/Library/LaunchAgents/com.cheongyak.lh.plist
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${CHEONG_PY:-$(command -v python3)}"
[ -x /opt/miniconda3/envs/Jisangfolio/bin/python3 ] && PY=/opt/miniconda3/envs/Jisangfolio/bin/python3
PL="$HOME/Library/LaunchAgents/com.cheongyak.lh.plist"
mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cheongyak.lh</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/scripts/mac-run.sh</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>CHEONG_PY</key><string>$PY</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>7</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>7</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$DIR/logs/mac-run.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/mac-run.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/com.cheongyak.lh" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PL"
echo "설치 완료: $PL (python: $PY)"
launchctl print "gui/$(id -u)/com.cheongyak.lh" | grep -E "state|path" | head -3
