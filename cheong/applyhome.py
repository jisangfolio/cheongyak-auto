"""청약홈 APT 분양 공고 알리미 (공공데이터포털 오픈API).

- 관심 지역의 '새 공고'를 감지해 알림
- 청약 접수일이 임박한 공고를 리마인더로 알림
실제 청약 신청(인증서·자격판정)은 자동화 대상이 아니며 사람이 직접 한다.
"""
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

API_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
SEEN_FILE = Path(__file__).resolve().parent.parent / ".seen_pblanc.json"


def _get_json(params, timeout=30, retries=3, backoff=3):
    """공공데이터 API GET(JSON). 일시적 네트워크 오류/타임아웃은 재시도한다.

    공공데이터포털은 순간적으로 느리거나 5xx를 내는 일이 잦아, 하루 1회 실행이
    한 번의 타임아웃으로 죽지 않도록 지수 백오프로 재시도한다.
    """
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(API_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last = e
            if attempt < retries:
                wait = backoff * attempt
                print(f"[applyhome] API 재시도 {attempt}/{retries} ({wait}s 후): {e}")
                time.sleep(wait)
    raise last


def _fetch_all(service_key, per_page=500, max_pages=40):
    items, page = [], 1
    while page <= max_pages:
        body = _get_json({"page": page, "perPage": per_page,
                          "serviceKey": service_key, "returnType": "JSON"})
        data = body.get("data", []) or []
        items.extend(data)
        total = body.get("totalCount", 0)
        if not data or page * per_page >= total:
            break
        page += 1
    return items


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def _save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def _record(it):
    return {
        "name": it.get("HOUSE_NM", ""),
        "area": it.get("SUBSCRPT_AREA_CODE_NM", "") or "",
        "type": it.get("HOUSE_DTL_SECD_NM") or it.get("HOUSE_SECD_NM", ""),
        "addr": it.get("HSSPLY_ADRES", ""),
        "households": it.get("TOT_SUPLY_HSHLDCO", ""),
        "notice_de": it.get("RCRIT_PBLANC_DE", ""),
        "begin": it.get("RCEPT_BGNDE", ""),
        "end": it.get("RCEPT_ENDDE", ""),
        "award": it.get("PRZWNER_PRESNATN_DE", ""),
        "url": it.get("PBLANC_URL") or it.get("HMPG_ADRES", ""),
        "pno": str(it.get("PBLANC_NO", "") or it.get("HOUSE_MANAGE_NO", "")),
    }


def find_matches(config):
    """(new_notices, upcoming, first_run) 반환."""
    ah = config["applyhome"]
    regions = ah.get("regions") or []
    types = ah.get("house_types") or []
    remind_days = int(ah.get("remind_days_before", 3))
    today = date.today()

    items = _fetch_all(ah["service_key"], int(ah.get("per_page", 500)))
    seen = _load_seen()
    first_run = not seen

    new_notices, upcoming = [], []
    for it in items:
        rec = _record(it)
        if regions and not any(rg in rec["area"] for rg in regions):
            continue
        if types and not any(t in rec["type"] for t in types):
            continue

        begin = _parse_date(rec["begin"])
        end = _parse_date(rec["end"])
        active = end is None or end >= today
        if not rec["pno"] or not active:
            continue

        # 접수 임박(오늘 ~ remind_days 이내 시작)
        if begin and today <= begin <= today + timedelta(days=remind_days):
            upcoming.append(rec)

        # 새 공고(처음 본 것)
        if rec["pno"] not in seen:
            if not first_run:
                new_notices.append(rec)
            seen.add(rec["pno"])

    _save_seen(seen)
    return new_notices, upcoming, first_run


def format_report(new_notices, upcoming):
    lines = []
    if new_notices:
        lines.append(f"🆕 새 청약 공고 {len(new_notices)}건 (관심지역)\n")
        lines += [_fmt(r) for r in new_notices]
    if upcoming:
        lines.append(f"\n⏰ 청약 접수 임박 {len(upcoming)}건\n")
        lines += [_fmt(r) for r in upcoming]
    return "\n".join(lines).strip()


def _fmt(r):
    return (
        f"[{r['type']}] {r['name']}\n"
        f" · 지역: {r['area']}  ({r['addr']})\n"
        f" · 모집공고일: {r['notice_de']}\n"
        f" · 청약접수: {r['begin']} ~ {r['end']}\n"
        f" · 당첨발표: {r['award']}\n"
        f" · 공급세대: {r['households']}\n"
        f" · 링크: {r['url']}\n"
    )
