#!/bin/bash
# Mac 자동 실행 설치 (한 번만): 매일 09:07, 18:07 에 LH 수집(scripts/mac-run.sh)
#
# macOS 는 launchd 작업이 Desktop·Documents·Downloads 안의 파일을 못 읽게 막는다(Operation not permitted).
# 그래서 실행용 복사본을 ~/.cheongyak-auto 에 git clone 하고 .env·profile.json 을 복사해 거기서 돌린다.
# (코드는 실행 때마다 git pull 로 최신화된다. .env·profile.json 을 바꾸면 이 스크립트를 다시 실행)
# 제거: launchctl bootout gui/$(id -u)/com.cheongyak.lh; rm ~/Library/LaunchAgents/com.cheongyak.lh.plist; rm -rf ~/.cheongyak-auto
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${CHEONG_RUN_DIR:-$HOME/.cheongyak-auto}"
PY="${CHEONG_PY:-$(command -v python3)}"
[ -x /opt/miniconda3/envs/Jisangfolio/bin/python3 ] && PY=/opt/miniconda3/envs/Jisangfolio/bin/python3
URL="$(git -C "$SRC" remote get-url origin)"

if [ -d "$RUN/.git" ]; then
  git -C "$RUN" pull -q --ff-only origin main
else
  git clone -q "$URL" "$RUN"
fi
for f in .env profile.json; do [ -f "$SRC/$f" ] && cp "$SRC/$f" "$RUN/$f" && chmod 600 "$RUN/$f"; done
git -C "$RUN" config user.name  "$(git -C "$SRC" config user.name)"
git -C "$RUN" config user.email "$(git -C "$SRC" config user.email)"
mkdir -p "$RUN/logs" "$HOME/Library/LaunchAgents"

PL="$HOME/Library/LaunchAgents/com.cheongyak.lh.plist"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cheongyak.lh</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RUN/scripts/mac-run.sh</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>CHEONG_PY</key><string>$PY</string>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>7</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>7</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$RUN/logs/mac-run.log</string>
  <key>StandardErrorPath</key><string>$RUN/logs/mac-run.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/com.cheongyak.lh" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PL"
echo "설치 완료: $PL"
echo "  실행 폴더: $RUN   python: $PY   로그: $RUN/logs/mac-run.log"
