"""알림 이력 — 이미 알린 공고와 보낸 리마인더를 state/state.json 에 남긴다.

GitHub Actions 에서는 실행이 끝날 때 이 파일을 커밋해 다음 실행이 이어받는다.
(공고 id·날짜만 들어 있고 개인정보는 없다.)
"""
import json
from datetime import timedelta
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "state.json"
KEEP_DAYS = 180


class State:
    def __init__(self, path=STATE_FILE):
        self.path = Path(path)
        data = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        self.seen = data.get("seen", {})          # key -> 처음 본 날짜
        self.reminded = data.get("reminded", {})  # key -> ["begin", "end"]
        self.initialized = bool(data.get("initialized"))
        self.zero = data.get("zero", {})          # 수집처 -> 연속 0건 횟수

    def is_new(self, key):
        return key not in self.seen

    def mark_seen(self, key, today):
        self.seen.setdefault(key, today.isoformat())

    def was_reminded(self, key, what):
        return what in self.reminded.get(key, [])

    def mark_reminded(self, key, what):
        self.reminded.setdefault(key, [])
        if what not in self.reminded[key]:
            self.reminded[key].append(what)

    def save(self, today):
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        self.seen = {k: d for k, d in self.seen.items() if d >= cutoff}
        self.reminded = {k: v for k, v in self.reminded.items() if k in self.seen}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"initialized": True, "zero": self.zero, "seen": dict(sorted(self.seen.items())), "reminded": self.reminded},
            ensure_ascii=False, indent=1), encoding="utf-8")
