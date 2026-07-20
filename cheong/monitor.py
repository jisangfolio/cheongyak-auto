"""오픈 감지: 응모/청약이 열렸는지 판단.

open_detection:
  mode: http | playwright     # http=가벼움(정적), playwright=JS 렌더링 필요할 때
  rule: keyword_present | keyword_absent | url_status
        | selector_present | selector_enabled   (뒤 2개는 playwright 전용)
  value: 감지 기준값
"""
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _check_http(target):
    det = target["open_detection"]
    rule = det["rule"]
    r = requests.get(target["url"], timeout=15, headers=_HEADERS)
    if rule == "keyword_present":
        return det["value"] in r.text
    if rule == "keyword_absent":
        return det["value"] not in r.text
    if rule == "url_status":
        return r.status_code == int(det.get("value", 200))
    raise ValueError(f"http 모드에서 지원하지 않는 rule: {rule}")


def _check_playwright(target):
    from playwright.sync_api import sync_playwright

    det = target["open_detection"]
    rule = det["rule"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=_HEADERS["User-Agent"])
        try:
            page.goto(target["url"], timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if rule == "selector_present":
                return page.locator(det["value"]).count() > 0
            if rule == "selector_enabled":
                loc = page.locator(det["value"]).first
                return loc.count() > 0 and loc.is_enabled()
            if rule == "keyword_present":
                return det["value"] in page.content()
            if rule == "keyword_absent":
                return det["value"] not in page.content()
            raise ValueError(f"playwright 모드에서 지원하지 않는 rule: {rule}")
        finally:
            browser.close()


def is_open(target):
    mode = target["open_detection"].get("mode", "playwright")
    return _check_http(target) if mode == "http" else _check_playwright(target)
