"""LH(한국토지주택공사) 분양임대공고문 API 연동.

청약홈(분양)이 못 잡는 **LH 임대주택**(국민임대·행복주택·영구임대·전세임대 등)을 잡는다.
- API: apis.data.go.kr/B552555/lhLeaseNoticeInfo1 (data.go.kr 같은 키, 별도 활용신청)
- 응답: [{"dsSch":[검색조건]}, {"dsList":[공고목록]}]
- 목록 API라 접수시작일·세대수·주소는 없음(상세 API 미연동). 공고명·지역·유형·게시일·마감일·URL 제공.
- UPP_AIS_TP_CD: 05=분양주택(청약홈과 중복→기본 제외), 06=임대주택
"""
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

LH_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LH_SEEN_FILE = Path(__file__).resolve().parent.parent / ".seen_lh.json"
DEFAULT_UPP_TYPES = ("06",)  # 임대주택만(분양은 청약홈이 커버)


def _get(params, timeout=30, retries=3, backoff=3):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(LH_URL, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last = e
            if attempt < retries:
                print(f"[lh] API 재시도 {attempt}/{retries}: {e}")
                time.sleep(backoff * attempt)
    raise last


def _parse_lh_date(s):
    if not s:
        return None
    s = str(s).strip().replace(".", "").replace("-", "")[:8]
    try:
        if len(s) == 8:
            return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None
    return None


def _dslist(body):
    """LH 응답에서 dsList(공고목록) 추출."""
    if isinstance(body, list):
        for seg in body:
            if isinstance(seg, dict) and seg.get("dsList"):
                return seg["dsList"]
    return []


def _record(it):
    """LH 응답 항목 → 공통 record 스키마(청약홈과 동일 키)."""
    return {
        "pno": str(it.get("PAN_ID", "")),
        "name": it.get("PAN_NM", ""),
        "area": it.get("CNP_CD_NM", "") or "",
        "type": it.get("AIS_TP_CD_NM", "") or it.get("UPP_AIS_TP_NM", ""),
        "addr": "",
        "households": "",
        "notice_de": it.get("PAN_NT_ST_DT", "") or it.get("PAN_DT", ""),
        "begin": "",                       # 목록 API엔 접수시작일 없음
        "end": it.get("CLSG_DT", ""),      # 마감일
        "award": "",
        "url": it.get("DTL_URL", ""),
        "source": "LH",
    }


def _fetch_all(service_key, upp_types=DEFAULT_UPP_TYPES, per_page=100, max_pages=20):
    out = []
    for upp in upp_types:
        page = 1
        while page <= max_pages:
            body = _get({"serviceKey": service_key, "PG_SZ": per_page,
                         "PAGE": page, "UPP_AIS_TP_CD": upp})
            data = _dslist(body)
            out.extend(data)
            if not data:
                break
            try:
                total = int(data[0].get("ALL_CNT", 0))
            except (ValueError, TypeError):
                total = 0
            if page * per_page >= total:
                break
            page += 1
    return out


def _load_seen():
    if LH_SEEN_FILE.exists():
        return set(json.loads(LH_SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def _save_seen(seen):
    LH_SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")


def fetch_records(config):
    """관심지역으로 필터한 LH 임대 공고 record 리스트(대시보드/DB 적재용)."""
    lh = config.get("lh") or {}
    key = lh.get("service_key") or config.get("applyhome", {}).get("service_key")
    regions = lh.get("regions") or config.get("applyhome", {}).get("regions") or []
    types = tuple(lh.get("upp_types", DEFAULT_UPP_TYPES))
    out = []
    for it in _fetch_all(key, types):
        rec = _record(it)
        if regions and not any(rg in rec["area"] for rg in regions):
            continue
        if rec["pno"]:
            out.append(rec)
    return out


def find_lh_matches(config):
    """(new_notices, upcoming, first_run) — 청약홈 find_matches 와 동일 인터페이스.

    upcoming 은 접수시작일이 없어 '마감(CLSG_DT) 임박' 기준으로 잡는다.
    """
    lh = config.get("lh") or {}
    remind_days = int(lh.get("remind_days_before",
                             config.get("applyhome", {}).get("remind_days_before", 3)))
    today = date.today()

    records = fetch_records(config)
    seen = _load_seen()
    first_run = not seen

    new_notices, upcoming = [], []
    for rec in records:
        end = _parse_lh_date(rec["end"])
        if end is not None and end < today:   # 이미 마감
            continue
        if end and today <= end <= today + timedelta(days=remind_days):
            upcoming.append(rec)
        if rec["pno"] not in seen:
            if not first_run:
                new_notices.append(rec)
            seen.add(rec["pno"])

    _save_seen(seen)
    return new_notices, upcoming, first_run
