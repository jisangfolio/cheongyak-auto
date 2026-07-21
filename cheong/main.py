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
    """청약가점 총점 계산(만 30세 규칙 반영). 실패 시 None."""
    try:
        from . import eligibility
        return eligibility.gajeom(_cheong_cfg(config))["total"]
    except Exception:  # noqa: BLE001
        return None


def _brief_profile(config):
    """브리핑용 사용자 프로필(무주택 산정기간·청약가점 포함)."""
    from . import eligibility
    c = _cheong_cfg(config)
    nh = eligibility.no_house_counted_years(c)
    profile = {
        "무주택기간": (f"{nh}년(가점 산정)" if nh is not None else c.get("무주택")),
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
def _apt_body(config, new_notices, upcoming):
    """지원가치 필터를 적용해 이메일 본문 생성. (본문, 유지건수, 제외건수) 반환."""
    from .applyhome import _fmt
    from . import applicability as ap
    profile = _cheong_cfg(config)
    excluded, out = [], []

    def _section(title_fmt, recs):
        kept = []
        for r in recs:
            v = ap.applicability(r, profile)
            if not v["worth"]:
                excluded.append(f"· {str(r.get('name', ''))[:34]} — {v['reason']}")
                continue
            block = _fmt(r).rstrip() + "\n · " + ap.one_liner(r, profile)
            if v.get("note"):
                block += "\n · ▸ " + v["note"]
            kept.append(block)
        if kept:
            out.append(title_fmt.format(n=len(kept)))
            out.append("")
            out.append("\n\n".join(kept))
        return len(kept)

    n = _section("🆕 새 청약 공고 {n}건 (지원가치 필터 통과)", new_notices)
    n += _section("\n⏰ 청약 접수 임박 {n}건", upcoming)
    if excluded:
        out.append("\n── 지원 불가로 제외 ──")
        out.append("\n".join(excluded))
    return "\n".join(out).strip(), n, len(excluded)


def cmd_apt_watch(config, args):  # noqa: ARG001
    new_notices, upcoming, first_run = find_matches(config)  # 청약홈(분양)
    if (config.get("lh") or {}).get("enabled"):              # LH(임대) 추가
        try:
            from . import lh
            n2, u2, _ = lh.find_lh_matches(config)
            new_notices += n2
            upcoming += u2
        except Exception as e:  # noqa: BLE001
            print(f"[apt] LH 조회 건너뜀: {e}")
    try:
        from . import db
        db.init_db()
        db.upsert_notices(new_notices + upcoming)
    except Exception as e:  # noqa: BLE001
        print(f"[apt] DB 반영 건너뜀: {e}")

    if first_run:
        print("[apt] 최초 실행 — 현재 관심지역 공고를 기준선으로 저장했습니다. "
              "다음부터 '새 공고'만 알립니다.")
        body, kept, _ = _apt_body(config, [], upcoming)
        if kept:
            notify(config, "⏰ 청약 접수 임박", body)
        return
    if not new_notices and not upcoming:
        print("[apt] 새 공고/임박 건 없음.")
        return
    body, kept, excl = _apt_body(config, new_notices, upcoming)
    if not kept:
        print(f"[apt] 새/임박 공고는 있으나 지원가치 있는 건 없음(구조적 제외 {excl}건).")
        return
    title = f"🏠 청약 알림 (지원가치 {kept}건" + (f" · 제외 {excl}" if excl else "") + ")"
    notify(config, title, body)


def cmd_match(config, args):  # noqa: ARG001
    from . import applicability as ap, db
    profile = _cheong_cfg(config)
    regions = config.get("applyhome", {}).get("regions")
    active = db.get_notices(regions=regions, active_only=True)
    yes, no = [], []
    for r in active:
        (yes if ap.applicability(r, profile)["worth"] else no).append(r)
    print(f"활성 공고 {len(active)}건 → 지원가치 {len(yes)}건 / 구조적 제외 {len(no)}건\n")
    for r in yes:
        v = ap.applicability(r, profile)
        print(f"✅ [{r.get('type', '')}] {str(r.get('name', ''))[:36]}  ({r.get('area', '')})")
        print(f"     {' / '.join(v['paths'])}")
    if no:
        print("\n── 구조적 제외(지원 경로 없음) ──")
        for r in no:
            print(f"⛔ {str(r.get('name', ''))[:36]} — {ap.applicability(r, profile)['reason']}")


def cmd_sync_db(config, args):  # noqa: ARG001
    from . import db
    db.init_db()
    migrated = db.migrate_seen_file(_SEEN_FILE)
    records = _fetch_region_records(config)
    if (config.get("lh") or {}).get("enabled"):
        try:
            from . import lh
            records += lh.fetch_records(config)
        except Exception as e:  # noqa: BLE001
            print(f"[db] LH 조회 건너뜀: {e}")
    n = db.upsert_notices(records)
    print(f"[db] 공고 {n}건 저장 · seen {migrated}건 이관 → {db.DEFAULT_DB}")


def cmd_gajeom(config, args):  # noqa: ARG001
    from . import eligibility
    c = _cheong_cfg(config)
    nh = eligibility.no_house_counted_years(c)
    r = eligibility.gajeom(c)
    b, d = r["breakdown"], r.get("detail", {})
    print(f"청약가점: {r['total']} / {r['max']}점   (무주택 산정기간 {nh}년)")
    print(f"  · 무주택기간   {b['no_house']:>2}점  {d.get('no_house', '')}")
    print(f"  · 부양가족수   {b['dependents']:>2}점  {d.get('dependents', '')}")
    print(f"  · 통장가입기간 {b['account']:>2}점  {d.get('account', '')}")
    if nh == 0.0:
        print("※ 만 30세 미만 미혼이면 무주택 가점은 0으로 산정됩니다(평생 무주택이어도).")
    print("※ 값 수정: config.yaml 의 '청약' 항목")


def cmd_eligibility(config, args):
    from . import eligibility
    pno = getattr(args, "pno", None)
    record = _find_notice(pno) if pno else None
    if pno and not record:
        print(f"[eligibility] DB에 공고번호 {pno} 없음 → 프로필 기준 일반 결과로 출력.\n")
    print(eligibility.summarize(eligibility.check_eligibility(_cheong_cfg(config), record)))


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
    sub.add_parser("match", help="활성 공고별 '지원 가치' 필터(구조적 불가 제외)")
    pe = sub.add_parser("eligibility", help="청약 자격 사전체크(선택: 공고번호)")
    pe.add_argument("pno", nargs="?")
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
        "match": cmd_match,
        "eligibility": cmd_eligibility,
        "brief": cmd_brief,
        "predict": cmd_predict,
        "test-notify": cmd_test_notify,
        "watch": cmd_watch,
        "fill": cmd_fill,
    }
    handlers[args.cmd](config, args)


if __name__ == "__main__":
    main()
