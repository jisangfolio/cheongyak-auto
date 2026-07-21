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
# 상세정보 API(2026-07-21 라이브 검증). operation 은 getLeaseNoticeDtlInfo1(경로 반복 아님).
LH_DTL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"
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
    """LH 응답 항목 → 공통 record 스키마(청약홈과 동일 키).

    상세 API 연결코드(_ccr/_spl/_upp/_ais)를 transient 키로 함께 실어,
    이후 enrich 단계에서 상세정보(접수시작·발표일·주소 등)를 채운다.
    (`_` 접두 키는 DB 컬럼에 저장되지 않는다.)
    """
    return {
        "pno": str(it.get("PAN_ID", "")),
        "name": it.get("PAN_NM", ""),
        "area": it.get("CNP_CD_NM", "") or "",
        "type": it.get("AIS_TP_CD_NM", "") or it.get("UPP_AIS_TP_NM", ""),
        "addr": "",
        "households": "",
        "notice_de": it.get("PAN_NT_ST_DT", "") or it.get("PAN_DT", ""),
        "begin": "",                       # 목록 API엔 접수시작일 없음 → 상세에서 채움
        "end": it.get("CLSG_DT", ""),      # 마감일
        "award": "",                       # 상세에서 당첨발표일 채움
        "url": it.get("DTL_URL", ""),
        "source": "LH",
        # 상세 API 연결코드(transient).
        "_ccr": str(it.get("CCR_CNNT_SYS_DS_CD", "") or ""),
        "_spl": str(it.get("SPL_INF_TP_CD", "") or ""),
        "_upp": str(it.get("UPP_AIS_TP_CD", "") or ""),
        "_ais": str(it.get("AIS_TP_CD", "") or ""),
    }


def _dtl_get(params, timeout=15):
    """LH 상세 API 호출(단발, 조용한 실패). 응답 데이터셋 리스트 반환."""
    try:
        r = requests.get(LH_DTL_URL, params=params, timeout=timeout)
        r.raise_for_status()
        body = r.json()
        return body if isinstance(body, list) else []
    except (requests.exceptions.RequestException, ValueError):
        return []


def _seg(datasets, name):
    """상세 응답(list of dict)에서 특정 데이터셋(rows)만 뽑는다."""
    for seg in datasets:
        if isinstance(seg, dict) and name in seg and isinstance(seg[name], list):
            return seg[name]
    return []


def fetch_detail(service_key, rec, timeout=15):
    """LH 상세정보 조회 → 접수시작·발표일·주소·공고문링크·접수방법 dict 반환.

    실패/데이터 없음이면 {} 반환(파이프라인이 죽지 않도록 방어적).
    여러 단지가 묶인 공고는 접수시작=최소, 마감=최대로 집계한다.
    """
    if not service_key or not rec.get("pno"):
        return {}
    params = {
        "serviceKey": service_key,
        "PAN_ID": rec["pno"],
        "CCR_CNNT_SYS_DS_CD": rec.get("_ccr", "") or "03",
        "SPL_INF_TP_CD": rec.get("_spl", ""),
        "UPP_AIS_TP_CD": rec.get("_upp", "") or "06",
        "AIS_TP_CD": rec.get("_ais", ""),
    }
    ds = _dtl_get(params, timeout=timeout)
    if not ds:
        return {}

    scdl = _seg(ds, "dsSplScdl")     # 공급일정(접수/발표)
    sbd = _seg(ds, "dsSbd")          # 단지정보(주소/세대/면적)
    ahfl = _seg(ds, "dsAhflInfo")    # 첨부(공고문 파일)
    ctrt = _seg(ds, "dsCtrtPlc")     # 접수처/접수방법

    def _norm_date(s):
        """'20260807'·'2026-08-07' 등을 'YYYY.MM.DD'로 통일(파싱 실패 시 원본)."""
        d = _parse_lh_date(s)
        return d.strftime("%Y.%m.%d") if d else str(s).strip()

    def _dates(rows, key):
        vals = [_norm_date(r.get(key, "")) for r in rows if str(r.get(key, "")).strip()]
        return sorted(v for v in vals if v)

    begins = _dates(scdl, "SBSC_ACP_ST_DT")
    ends = _dates(scdl, "SBSC_ACP_CLSG_DT")
    awards = _dates(scdl, "PZWR_ANC_DT")

    complexes = [{
        "name": str(r.get("LCC_NT_NM", "")).strip(),
        "addr": str(r.get("LGDN_ADR", "")).strip(),
        "total_households": str(r.get("HSH_CNT", "")).strip(),
        "area": str(r.get("DDO_AR", "")).strip(),
        "movein": str(r.get("MVIN_XPC_YM", "")).strip(),
    } for r in sbd]

    files = [{
        "label": str(r.get("SL_PAN_AHFL_DS_CD_NM", "") or "공고문").strip(),
        "url": str(r.get("AHFL_URL", "")).strip(),
    } for r in ahfl if str(r.get("AHFL_URL", "")).strip()]

    apply_places = [{
        "place": str(r.get("CTRT_PLC_DTL_ADR", "")).strip()
        or str(r.get("CTRT_PLC_ADR", "")).strip(),
        "guide": str(r.get("SIL_OFC_GUD_FCTS", "")).strip(),
        "tel": str(r.get("SIL_OFC_TLNO", "")).strip(),
    } for r in ctrt]

    detail = {
        "begin": min(begins) if begins else "",
        "end": max(ends) if ends else "",
        "award": awards[0] if awards else "",
        "addr": complexes[0]["addr"] if complexes else "",
        "complexes": complexes,
        "files": files,
        "apply_places": apply_places,
    }
    return detail


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


def _enrich(rec, key):
    """상세 API로 rec 를 보강(접수시작·발표일·주소 + detail_json). 실패 시 원본 유지."""
    try:
        d = fetch_detail(key, rec)
    except Exception:  # noqa: BLE001
        d = {}
    if not d:
        return
    if d.get("begin"):
        rec["begin"] = d["begin"]
    if d.get("end"):
        rec["end"] = d["end"]
    if d.get("award"):
        rec["award"] = d["award"]
    if d.get("addr"):
        rec["addr"] = d["addr"]
    # 공고문 링크·접수방법 등 부가정보는 JSON 문자열로 실어 DB/UI 에서 재사용.
    rec["detail_json"] = json.dumps({
        "complexes": d.get("complexes", []),
        "files": d.get("files", []),
        "apply_places": d.get("apply_places", []),
    }, ensure_ascii=False)


def fetch_records(config, enrich=True, enrich_limit=40):
    """관심지역으로 필터한 LH 임대 공고 record 리스트(대시보드/DB 적재용).

    enrich=True 면 아직 마감 전(활성) 공고에 한해 상세 API 로 접수시작·발표일·
    주소·공고문링크·접수방법을 채운다(enrich_limit 건까지, 각 조용한 실패).
    """
    lh = config.get("lh") or {}
    key = lh.get("service_key") or config.get("applyhome", {}).get("service_key")
    regions = lh.get("regions") or config.get("applyhome", {}).get("regions") or []
    types = tuple(lh.get("upp_types", DEFAULT_UPP_TYPES))
    today = date.today()
    out = []
    for it in _fetch_all(key, types):
        rec = _record(it)
        if regions and not any(rg in rec["area"] for rg in regions):
            continue
        if rec["pno"]:
            out.append(rec)

    if enrich and key:
        done = 0
        for rec in out:
            if done >= enrich_limit:
                break
            end = _parse_lh_date(rec["end"])
            if end is not None and end < today:
                continue  # 이미 마감된 공고는 발표일/접수일 보강 불필요
            _enrich(rec, key)
            done += 1
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
