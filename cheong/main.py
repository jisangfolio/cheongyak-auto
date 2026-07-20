"""CLI 진입점.

사용법:
  python -m cheong.main test-notify                 # 알림 설정 점검
  python -m cheong.main watch <타겟> [--interval 60] [--autofill]
  python -m cheong.main fill  <타겟>                # 지금 바로 폼 자동입력
"""
import argparse
import time

from .applyhome import find_matches, format_report
from .autofill import run_fill
from .config import get_target, load_config
from .monitor import is_open
from .notify import notify


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


def cmd_apt_watch(config, args):  # noqa: ARG001
    new_notices, upcoming, first_run = find_matches(config)
    if first_run:
        print("[apt] 최초 실행 — 현재 관심지역 공고를 기준선으로 저장했습니다. "
              "다음부터 '새 공고'만 알립니다.")
        if upcoming:
            body = format_report([], upcoming)
            notify(config, "⏰ 청약 접수 임박", body)
        return
    if not new_notices and not upcoming:
        print("[apt] 새 공고/임박 건 없음.")
        return
    body = format_report(new_notices, upcoming)
    title = f"🏠 청약 알림 (새 {len(new_notices)} · 임박 {len(upcoming)})"
    notify(config, title, body)


def cmd_test_notify(config, args):  # noqa: ARG001
    notify(config, "테스트 알림", "알림 설정이 정상 동작합니다 ✅")


def main():
    parser = argparse.ArgumentParser(description="청약/응모 반자동화 도구")
    parser.add_argument("-c", "--config", default="config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pw = sub.add_parser("watch", help="오픈 감시 → 알림 (+선택적 자동입력)")
    pw.add_argument("target")
    pw.add_argument("--interval", type=int)
    pw.add_argument("--autofill", action="store_true", help="열리면 폼 자동입력까지 실행")

    pf = sub.add_parser("fill", help="지금 바로 폼 자동입력")
    pf.add_argument("target")

    sub.add_parser("apt-watch", help="청약홈 아파트 공고 확인 → 새 공고/임박 알림")
    sub.add_parser("test-notify", help="알림 설정 테스트")

    args = parser.parse_args()
    config = load_config(args.config)

    handlers = {
        "watch": cmd_watch,
        "fill": cmd_fill,
        "apt-watch": cmd_apt_watch,
        "test-notify": cmd_test_notify,
    }
    handlers[args.cmd](config, args)


if __name__ == "__main__":
    main()
