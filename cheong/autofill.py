"""폼 자동입력. 캡차/본인인증/인증서가 감지되면 사람에게 넘김.

steps 항목 예:
  - {action: wait_for, selector: "#form"}          # 요소 뜰 때까지 대기
  - {action: fill, selector: "#name", value_from: profile.name}
  - {action: fill, selector: "#phone", value: "010-0000-0000"}
  - {action: check, selector: "#agree"}
  - {action: select, selector: "#region", value: "서울"}
  - {action: click, selector: "button.next"}
  - {action: wait, value: 1000}                    # ms 대기
"""
from .config import resolve_value


def run_fill(config, target):
    from playwright.sync_api import sync_playwright

    stop_selectors = target.get("stop_on", [])
    submit = target.get("submit", {"mode": "manual"})

    with sync_playwright() as p:
        # 사람이 인증·제출을 이어받아야 하므로 화면 있는(headed) 브라우저
        browser = p.chromium.launch(headless=False)
        page = browser.new_context().new_page()
        page.goto(target["url"], timeout=60000, wait_until="domcontentloaded")
        print(f"[fill] 페이지 열림: {target['url']}")

        def hit_stop_gate():
            for ss in stop_selectors:
                try:
                    if page.locator(ss).count() > 0:
                        print(f"\n[fill] ⚠️ 인증/캡차 감지: '{ss}' → 사람에게 넘김")
                        return True
                except Exception:  # noqa: BLE001
                    pass
            return False

        for i, step in enumerate(target.get("steps", []), 1):
            action = step["action"]
            sel = step.get("selector")
            print(f"[fill] {i}. {action} {sel or ''}")
            try:
                if action == "fill":
                    val = resolve_value(step["value_from"], config) if "value_from" in step else step.get("value")
                    page.fill(sel, str(val))
                elif action == "click":
                    page.click(sel)
                elif action == "check":
                    page.check(sel)
                elif action == "select":
                    page.select_option(sel, str(step["value"]))
                elif action == "press":
                    page.press(sel, str(step["value"]))
                elif action == "wait":
                    page.wait_for_timeout(int(step.get("value", 1000)))
                elif action == "wait_for":
                    page.wait_for_selector(sel, timeout=int(step.get("timeout", 15000)))
                else:
                    print(f"[fill] 알 수 없는 action 무시: {action}")
                page.wait_for_timeout(400)
            except Exception as e:  # noqa: BLE001
                print(f"[fill] 스텝 실패 ({action} {sel}): {e}")

            if hit_stop_gate():
                _handoff(page)
                browser.close()
                return

        # 최종 제출
        if submit.get("mode") == "auto" and submit.get("selector"):
            if hit_stop_gate():  # 제출 직전 마지막 안전확인
                _handoff(page)
                browser.close()
                return
            print("[fill] 자동 제출 클릭...")
            page.click(submit["selector"])
            print("[fill] ✅ 제출 완료. 결과를 직접 확인하세요.")
            page.wait_for_timeout(3000)
            input("확인 후 Enter → 브라우저 닫기: ")
        else:
            _handoff(page)
        browser.close()


def _handoff(page):  # noqa: ARG001
    print("\n" + "=" * 56)
    print("  나머지(본인인증 / 캡차 / 최종 제출)는 직접 진행하세요.")
    print("  완료 후 이 터미널에서 Enter → 브라우저가 닫힙니다.")
    print("=" * 56)
    input("> 완료하면 Enter... ")
