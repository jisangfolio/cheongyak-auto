"""알림 이력 — 이미 알린 공고와 보낸 리마인더를 state/state.json 에 남긴다.

GitHub Actions 에서는 실행이 끝날 때 이 파일을 커밋해 다음 실행이 이어받는다.
(공고 ID·날짜와 완료 확인에 필요한 디스코드 메시지·채널 ID를 저장한다.)
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
        self.reminded = data.get("reminded", {})  # key -> ["begin", "end", "end_today:<date>"]
        self.done = set(data.get("done", []))    # 완료된 공고 key
        self.tracked_messages = data.get("tracked_messages", {})  # 메시지 ID -> 채널 ID·공고 key
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

    def is_done(self, key):
        return key in self.done

    def mark_done(self, key):
        self.done.add(key)

    def track_message(self, key, channel_id, message_id):
        self.tracked_messages[message_id] = {"key": key, "channel_id": channel_id}

    def save(self, today):
        cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
        self.seen = {k: d for k, d in self.seen.items() if d >= cutoff}
        self.reminded = {k: v for k, v in self.reminded.items() if k in self.seen}
        self.tracked_messages = {mid: info for mid, info in self.tracked_messages.items()
                                 if info["key"] in self.seen and info["key"] not in self.done}
        data = {"initialized": True, "zero": self.zero, "seen": dict(sorted(self.seen.items())),
                "reminded": self.reminded}
        if self.done:
            data["done"] = sorted(self.done)
        if self.tracked_messages:
            data["tracked_messages"] = dict(sorted(self.tracked_messages.items()))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
