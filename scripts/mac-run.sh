#!/bin/bash
# Mac launchd 가 하루 2번 실행: LH 만 수집·알림 → state 커밋·push.
# (GitHub Actions 는 해외 IP 라 LH API 가 막혀 있어서 LH 는 Mac 이 맡는다)
cd "$(dirname "$0")/.." || exit 1
PY="${CHEONG_PY:-python3}"
echo "===== $(date '+%F %T') ====="
git pull -q --ff-only origin main || echo "[mac-run] pull 실패 — 로컬 변경 확인 필요"
CHEONG_ONLY=lh "$PY" -m cheong run
"$PY" -m cheong.sync "state: mac(lh) $(date +%F)"
