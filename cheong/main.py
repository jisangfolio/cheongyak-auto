"""CLI 진입점.

청약홈(아파트 청약) 명령:
  python -m cheong.main apt-watch      # 새 공고/접수임박 확인 → 이메일 알림 + DB 반영
  python -m cheong.main sync-db        # 관심지역 공고 전체를 DB에 적재(+기존 seen 이관)
  python -m cheong.main gajeom         # 청약가점 계산(config 의 '청약' 값 사용)
  python -m cheong.main brief <공고번호>   # LLM 공고 브리핑(키 없으면 템플릿)
  python -m cheong.main predict <공고번호> # 당첨 가능성 휴리스틱 추정
  python -m cheong.main test-notify    # 알림 설정 점검

응모 폼 자동입력(부가):
  python -m cheong.main watch <타겟> [--interval 60] [--autofill]
  python -m cheong.main fill  <타겟>
"""
import argparse
import time
from pathlib import Path

from .applyhome import find_matches, format_report
from .autofill import run_fill
from .config import get_target, load_config
from .monitor import is_open
from .notify import notify

_SEEN_FILE = Path(__file__).resolve().parent.parent / ".seen_pblanc.json"


# ---------- 공용 헬퍼 ----------
def _cheong_cfg(config):
    """config 의 '청약' 블록(무주택기간/부양가족/청약통장기간/희망지역)."""
    return config.get("청약", {}) or {}


def _my_gajeom(config):
    """config 값으로 청약가점 총점 계산. 실패 시 None."""
    try:
        from .gajeom import calc_gajeom
        c = _cheong_cfg(config)
        return calc_gajeom(
            c.get("무주택기간", 0), c.get("부양가족", 0), c.get("청약통장기간", 0)
        )["total"]
    except Exception:  # noqa: BLE001
        return None


def _brief_profile(config):
    """브리핑용 사용자 프로필(청약가점 포함)."""
    c = _cheong_cfg(config)
    profile = {
        "무주택기간": c.get("무주택기간"),
        "부양가족": c.get("부양가족"),
        "청약통장기간": c.get("청약통장기간"),
        "희망지역": c.get("희망지역"),
    }
    g = _my_gajeom(config)
    if g is not None:
        profile["청약가점"] = g
    return profile


def _fetch_region_records(config):
    """청약홈 API 에서 관심지역 공고 레코드를 모두 가져온다(applyhome 내부 재사용)."""
    from .applyhome import _fetch_all, _record
    ah = config["applyhome"]
    regions = ah.get("regions") or []
    items = _fetch_all(ah["service_key"], int(ah.get("per_page", 500)))
    out = []
    for it in items:
        rec = _record(it)
        if regions and not any(rg in rec["area"] for rg in regions):
            continue
        out.append(rec)
    return out


def _find_notice(pno):
    """DB 에서 공고번호로 레코드 1건을 찾는다(없으면 None)."""
    from . import db
    for n in db.get_notices():
        if str(n.get("pno")) == str(pno):
            return n
    return None


# ---------- 명령 ----------
def cmd_apt_watch(config, args):  # noqa: ARG001
    new_notices, upcoming, first_run = find_matches(config)
    # DB 에도 반영(대시보드/브리핑/예측이 읽음). 실패해도 알림 흐름은 유지.
    try:
        from . import db
        db.init_db()
        db.upsert_notices(new_notices + upcoming)
    except Exception as e:  # noqa: BLE001
        print(f"[apt] DB 반영 건너뜀: {e}")

    if first_run:
        print("[apt] 최초 실행 — 현재 관심지역 공고를 기준선으로 저장했습니다. "
              "다음부터 '새 공고'만 알립니다.")
        if upcoming:
            notify(config, "⏰ 청약 접수 임박", format_report([], upcoming))
        return
    if not new_notices and not upcoming:
        print("[apt] 새 공고/임박 건 없음.")
        return
    body = format_report(new_notices, upcoming)
    title = f"🏠 청약 알림 (새 {len(new_notices)} · 임박 {len(upcoming)})"
    notify(config, title, body)


def cmd_sync_db(config, args):  # noqa: ARG001
    from . import db
    db.init_db()
    migrated = db.migrate_seen_file(_SEEN_FILE)
    records = _fetch_region_records(config)
    n = db.upsert_notices(records)
    print(f"[db] 공고 {n}건 저장 · seen {migrated}건 이관 → {db.DEFAULT_DB}")


def cmd_gajeom(config, args):  # noqa: ARG001
    from .gajeom import calc_gajeom
    c = _cheong_cfg(config)
    r = calc_gajeom(c.get("무주택기간", 0), c.get("부양가족", 0), c.get("청약통장기간", 0))
    b, d = r["breakdown"], r.get("detail", {})
    print(f"청약가점: {r['total']} / {r['max']}점")
    print(f"  · 무주택기간   {b['no_house']:>2}점  {d.get('no_house', '')}")
    print(f"  · 부양가족수   {b['dependents']:>2}점  {d.get('dependents', '')}")
    print(f"  · 통장가입기간 {b['account']:>2}점  {d.get('account', '')}")
    print("※ 무주택기간·부양가족·통장기간은 config.yaml 의 '청약' 항목에서 수정")


def cmd_brief(config, args):
    from .briefing import brief_notice
    rec = _find_notice(args.pno)
    if not rec:
        print(f"[brief] DB에 공고번호 {args.pno} 없음. 먼저 'sync-db' 를 실행하세요.")
        return
    text = brief_notice(rec, _brief_profile(config), config.get("briefing", {}) or {})
    print(text)


def cmd_predict(config, args):
    from . import db
    from .predict import estimate_chance
    rec = _find_notice(args.pno)
    if not rec:
        print(f"[predict] DB에 공고번호 {args.pno} 없음. 먼저 'sync-db' 를 실행하세요.")
        return
    comp = db.get_competition(str(args.pno))
    r = estimate_chance(rec, comp, _my_gajeom(config))
    score = r.get("score")
    print(f"당첨 가능성(휴리스틱): {r['label']}" + (f"  ·  참고점수 {score}/100" if score is not None else ""))
    print(r.get("rationale", ""))
    print(f"⚠️ {r.get('caveat', '')}")


def cmd_watch(config, args):
    target = get_target(config, args.target)
    interval = args.interval or config.get("poll_interval_seconds", 60)
    print(f"[watch] '{target['name']}' 감시 시작 (간격 {interval}s). Ctrl+C 로 중단.")
    while True:
        try:
            if is_open(target):
                print("[watch] 🎯 응모 오픈 감지!")
                notify(config, "청약/응모 오픈!", f"{target['name']} 지금 열렸습니다.\n{target['url']}")
                if args.autofill:
                    run_fill(config, target)
                return
            print(f"[watch] 아직 안 열림 … {interval}s 후 재확인")
        except Exception as e:  # noqa: BLE001
            print(f"[watch] 확인 중 오류: {e}")
        time.sleep(interval)


def cmd_fill(config, args):
    run_fill(config, get_target(config, args.target))


def cmd_test_notify(config, args):  # noqa: ARG001
    notify(config, "테스트 알림", "알림 설정이 정상 동작합니다 ✅")


def main():
    parser = argparse.ArgumentParser(description="청약/응모 반자동화 도구")
    parser.add_argument("-c", "--config", default="config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("apt-watch", help="청약홈 공고 확인 → 새 공고/임박 알림 + DB 반영")
    sub.add_parser("sync-db", help="관심지역 공고 전체를 DB에 적재(+seen 이관)")
    sub.add_parser("gajeom", help="청약가점 계산(config '청약' 값 사용)")
    pb = sub.add_parser("brief", help="LLM 공고 브리핑(공고번호)")
    pb.add_argument("pno")
    pp = sub.add_parser("predict", help="당첨 가능성 휴리스틱 추정(공고번호)")
    pp.add_argument("pno")
    sub.add_parser("test-notify", help="알림 설정 테스트")

    pw = sub.add_parser("watch", help="응모 오픈 감시 → 알림 (+선택적 자동입력)")
    pw.add_argument("target")
    pw.add_argument("--interval", type=int)
    pw.add_argument("--autofill", action="store_true", help="열리면 폼 자동입력까지 실행")
    pf = sub.add_parser("fill", help="지금 바로 폼 자동입력")
    pf.add_argument("target")

    args = parser.parse_args()
    config = load_config(args.config)

    handlers = {
        "apt-watch": cmd_apt_watch,
        "sync-db": cmd_sync_db,
        "gajeom": cmd_gajeom,
        "brief": cmd_brief,
        "predict": cmd_predict,
        "test-notify": cmd_test_notify,
        "watch": cmd_watch,
        "fill": cmd_fill,
    }
    handlers[args.cmd](config, args)


if __name__ == "__main__":
    main()
