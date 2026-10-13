"""CLI.

  python -m cheong setup           처음 한 번: 설문 → profile.json
  python -m cheong run             수집 → 판정 → 새 공고·리마인더를 디스코드로 (상태 저장)
  python -m cheong run --dry-run   보내지 않고 화면에만 출력 (상태도 저장 안 함)
  python -m cheong preview         지금 진행 중인 공고 전체와 판정 이유(제외 포함) 보기
  python -m cheong test-discord    웹훅 연결 확인
"""
import argparse
import os
from datetime import timedelta
from pathlib import Path

import yaml

from . import discord, profile
from .eligibility import LEVELS, judge
from .sources import ALL
from .state import State
from .util import today_kst

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config():
    _load_dotenv()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    env = lambda k: os.environ.get(k, "").strip()   # Secret 붙여넣기 때 딸려 온 줄바꿈 제거
    cfg["keys"] = {"applyhome": env("APPLYHOME_KEY"), "lh": env("LH_KEY")}
    cfg["webhook"] = env("DISCORD_WEBHOOK_URL")
    return cfg


def collect(cfg, today):
    notices, report = [], {}
    for name, mod in ALL.items():
        if not cfg["sources"].get(name, {}).get("enabled", True):
            continue
        try:
            got = mod.fetch(cfg, today)
        except Exception as e:  # noqa: BLE001 - 한 수집처 실패가 전체를 막지 않게
            print(f"[{name}] 실패: {e}")
            got = []
        report[name] = len(got)
        notices.extend(got)
    print("[수집] " + ", ".join(f"{k} {v}건" for k, v in report.items()))
    return notices, report


def evaluate(notices, prof, today):
    """마감 안 된 공고만 판정해서 (공고, 판정) 목록으로."""
    out = []
    for n in notices:
        if n.is_closed(today):
            continue
        out.append((n, judge(n, prof, today)))
    return out


def plan(evaluated, prof, state, today):
    """보낼 것 정하기: (새 공고, 리마인더). 상태도 갱신한다."""
    min_score = LEVELS.get(prof.get("min_level", "확인"), 1)
    days = int(prof.get("remind_days", 2))
    new, remind = [], []
    for n, v in evaluated:
        if v.level == "무시":
            continue
        ok = v.score >= min_score
        if state.is_new(n.key):
            state.mark_seen(n.key, today)
            if ok:
                new.append((n, v))
            continue
        if not ok:
            continue
        if n.begin and today <= n.begin <= today + timedelta(days=days) \
                and not state.was_reminded(n.key, "begin"):
            state.mark_reminded(n.key, "begin")
            dd = (n.begin - today).days
            remind.append((n, v, "오늘 접수 시작!" if dd == 0 else f"접수 시작 D-{dd}"))
        elif n.end and today <= n.end <= today + timedelta(days=days) \
                and not state.was_reminded(n.key, "end") \
                and not (state.was_reminded(n.key, "begin") and n.begin
                         and (n.end - n.begin).days <= days):   # 짧은 접수는 한 번만
            state.mark_reminded(n.key, "end")
            dd = (n.end - today).days
            remind.append((n, v, "오늘 마감!" if dd == 0 else f"마감 D-{dd}"))
    new.sort(key=lambda x: (-x[1].score, x[0].begin or x[0].end or today))
    return new, remind


def cmd_run(args):
    cfg, prof, today = load_config(), profile.load(), today_kst()
    state = State()
    notices, report = collect(cfg, today)
    if not notices:
        msg = "⚠️ 모든 수집처에서 0건 — API 키나 접속 상태를 확인해 주세요. " + str(report)
        discord.send(cfg["webhook"], msg, dry_run=args.dry_run)
        return
    first = not state.initialized
    for src, cnt in report.items():                     # 수집처별 연속 0건 감시
        state.zero[src] = 0 if cnt else state.zero.get(src, 0) + 1
        if state.zero[src] == 3:
            discord.send(cfg["webhook"], f"⚠️ `{src}` 수집이 3회 연속 0건입니다. 사이트 구조 변경이나 "
                         "접속 차단일 수 있어요. Actions 로그를 확인해 주세요.", dry_run=args.dry_run)
    new, remind = plan(evaluate(notices, prof, today), prof, state, today)

    if new:
        head = (f"📋 처음 실행 — 지금 진행 중인 맞춤 공고 {len(new)}건" if first
                else f"🆕 새 맞춤 공고 {len(new)}건")
        discord.send(cfg["webhook"], head, [discord.embed(n, v) for n, v in new], args.dry_run)
    if remind:
        discord.send(cfg["webhook"], f"⏰ 리마인더 {len(remind)}건",
                     [discord.embed(n, v, h) for n, v, h in remind], args.dry_run)
    if not new and not remind:
        print("[run] 보낼 알림 없음")
    if not args.dry_run:
        state.save(today)


def cmd_preview(args):  # noqa: ARG001
    cfg, prof, today = load_config(), profile.load(), today_kst()
    notices, _ = collect(cfg, today)
    rows = evaluate(notices, prof, today)
    for lvl in ("추천", "확인", "제외"):
        part = [(n, v) for n, v in rows if v.level == lvl]
        print(f"\n===== {lvl} {len(part)}건 =====")
        for n, v in part:
            when = n.begin or n.end or n.posted
            print(f"[{n.source}] {n.title[:50]}  ({n.region or '-'}, {when})")
            print(f"    └ {' · '.join(v.reasons + v.tips)}")


def cmd_test(args):  # noqa: ARG001
    cfg = load_config()
    if not cfg["webhook"]:
        raise SystemExit("DISCORD_WEBHOOK_URL 이 없습니다 (.env 또는 환경변수)")
    discord.send(cfg["webhook"], "✅ 청약 알리미 연결 테스트 — 이 메시지가 보이면 성공입니다.")
    print("보냈습니다. 디스코드를 확인하세요.")


def main():
    ap = argparse.ArgumentParser(prog="cheong", description="내 조건 맞춤 청약 알리미")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="설문으로 프로필 만들기")
    s.add_argument("--print", action="store_true", help="Secret용 한 줄 JSON 출력")
    r = sub.add_parser("run", help="수집·판정·알림")
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("preview", help="진행 중 공고와 판정 이유 보기")
    sub.add_parser("test-discord", help="웹훅 테스트")
    args = ap.parse_args()
    if args.cmd == "setup":
        if args.print:
            import json
            print(json.dumps(profile.load(), ensure_ascii=False, separators=(",", ":")))
        else:
            profile.run_survey()
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "preview":
        cmd_preview(args)
    else:
        cmd_test(args)


if __name__ == "__main__":
    main()
