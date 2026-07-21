"""청약홈 청약접수 경쟁률 오픈API 클라이언트 (공공데이터포털 서비스 15098905).

- 특정 공고(주택관리번호/공고번호)의 청약 경쟁률을 조회해 정규화된 dict 로 반환한다.
- 실제 청약 신청은 자동화 대상이 아니며, 여기서는 참고용 경쟁률 정보만 가져온다.

⚠️ 이 서비스(15098905)는 분양정보 서비스(15098547)와 **별도**로
   data.go.kr 에서 활용신청(serviceKey 발급)이 필요하다.
✅ 엔드포인트/필드 2026-07-21 라이브 검증 완료(Swagger stage 36148).
   - 경로: api.odcloud.kr/api/ApplyhomeInfoCmpetRtSvc/v1/getAPTLttotPblancCmpet
   - 서버측 필터: cond[HOUSE_MANAGE_NO::EQ] / cond[PBLANC_NO::EQ] 정상 작동
   - 필드: HOUSE_TY(주택형) · SUPLY_HSHLDCO(공급세대) · REQ_CNT(접수건수)
           · CMPET_RATE(경쟁률; "(△15)" 형태면 15세대 미달) · RESIDE_SENM(해당/기타지역)
           · SUBSCRPT_RANK_CODE(순위)
⚠️ 이 데이터는 **접수 마감된 공고의 결과 경쟁률**이다(진행 중 공고는 마감 전까진 값 없음).
"""
from datetime import datetime

# 라이브 검증된 REST operation 경로(2026-07-21).
API_URL = (
    "https://api.odcloud.kr/api/ApplyhomeInfoCmpetRtSvc/v1"
    "/getAPTLttotPblancCmpet"
)


def _parse_date(s):
    """날짜 문자열을 date 로 파싱(실패 시 None). applyhome.py 와 동일 순서로 시도."""
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _norm(it):
    """경쟁률 원본 항목(dict)을 방어적으로 정규화한다.

    청약홈 경쟁률 API 는 주택형(HOUSE_TY)·공급세대·접수건수·경쟁률 등을
    항목별로 내려준다. 필드명이 서비스 개정으로 바뀔 수 있어 모두 .get 으로 접근하고,
    대안 필드명이 있으면 or 로 폴백한다.
    """
    return {
        # 식별자
        "house_manage_no": str(it.get("HOUSE_MANAGE_NO", "") or ""),
        "pblanc_no": str(it.get("PBLANC_NO", "") or ""),
        "name": it.get("HOUSE_NM", "") or "",
        # 주택형 / 공급 구분
        "house_type": (
            it.get("HOUSE_TY")
            or it.get("HOUSE_DTL_SECD_NM")
            or it.get("HOUSE_SECD_NM", "")
            or ""
        ),
        "supply_area": it.get("SUPLY_AR", "") or "",
        "supply_households": it.get("SUPLY_HSHLDCO", "")
        or it.get("TOT_SUPLY_HSHLDCO", "")
        or "",
        # 접수 / 경쟁률
        "req_cnt": it.get("REQ_CNT", "") or "",  # 접수(신청) 건수
        "competition_rate": (
            it.get("CMPET_RATE")
            or it.get("CMPET_RT")
            or it.get("LTTOT_CMPET_RATE", "")
            or ""
        ),
        # 지역/순위 등 부가 정보(검증된 실제 필드명 우선)
        "region": it.get("RESIDE_SENM", "")            # 해당지역/기타지역
        or it.get("SUBSCRPT_AREA_CODE_NM", "") or "",
        "rank": str(it.get("SUBSCRPT_RANK_CODE", "")   # 1/2 순위
                    or it.get("RANK_NM", "") or ""),
        "model_no": str(it.get("MODEL_NO", "") or ""),
        # 참고 날짜
        "rcept_ende": it.get("RCEPT_ENDDE", "") or "",
    }


def _parse_rate(raw):
    """CMPET_RATE 문자열을 (미달여부, 수치, 사람이 읽는 표기)로 해석.

    - "(△15)"  → (True, 15, "미달 15세대")   ← 미달(신청<공급)
    - "16.5"   → (False, 16.5, "16.5:1")
    - "" / None→ (False, None, "-")
    """
    s = str(raw or "").strip()
    if not s:
        return False, None, "-"
    if "△" in s:
        import re
        m = re.search(r"\d+", s)
        n = int(m.group(0)) if m else None
        return True, n, (f"미달 {n}세대" if n is not None else "미달")
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return False, None, s
    val = float(m.group(0))
    return False, val, f"{val:g}:1"


def fetch_rates_by_type(service_key, house_manage_no=None, pblanc_no=None,
                        per_page=300, timeout=20):
    """특정 공고의 **주택형별 경쟁률**을 집계한 리스트로 반환.

    반환 원소(경쟁률 낮은/미달 우선 정렬):
      {house_type, supply, req_cnt, rate_raw, rate_value,
       undersubscribed(bool), rate_text}
    데이터 없음/오류/식별자 미지정이면 [].

    ⚠️ 접수 마감된 공고의 결과값이다(진행 중 공고엔 아직 데이터 없음).
    """
    try:
        import requests
    except ImportError:
        return []
    if not service_key or not (house_manage_no or pblanc_no):
        return []

    params = {"page": 1, "perPage": per_page, "serviceKey": service_key,
              "returnType": "JSON"}
    if house_manage_no:
        params["cond[HOUSE_MANAGE_NO::EQ]"] = str(house_manage_no)
    if pblanc_no:
        params["cond[PBLANC_NO::EQ]"] = str(pblanc_no)

    try:
        r = requests.get(API_URL, params=params, timeout=timeout)
        r.raise_for_status()
        data = (r.json() or {}).get("data", []) or []
    except (requests.RequestException, ValueError):
        return []
    except Exception:
        return []

    # 주택형(HOUSE_TY) 단위로 집계: 공급세대=최대치, 접수건수=합산, 경쟁률=대표값.
    agg = {}
    for it in data:
        if not isinstance(it, dict):
            continue
        ht = str(it.get("HOUSE_TY", "") or "").strip()
        if not ht:
            continue
        cur = agg.setdefault(ht, {"supply": 0, "req_cnt": 0, "rate_raw": ""})
        try:
            cur["supply"] = max(cur["supply"], int(it.get("SUPLY_HSHLDCO", 0) or 0))
        except (TypeError, ValueError):
            pass
        try:
            cur["req_cnt"] += int(it.get("REQ_CNT", 0) or 0)
        except (TypeError, ValueError):
            pass
        if it.get("CMPET_RATE"):
            cur["rate_raw"] = it.get("CMPET_RATE")

    out = []
    for ht, v in agg.items():
        under, val, text = _parse_rate(v["rate_raw"])
        out.append({
            "house_type": ht,
            "supply": v["supply"],
            "req_cnt": v["req_cnt"],
            "rate_raw": v["rate_raw"],
            "rate_value": val,
            "undersubscribed": under,
            "rate_text": text,
        })

    # 미달(당첨 쉬움) → 낮은 경쟁률 → 높은 경쟁률 순.
    def _key(e):
        if e["undersubscribed"]:
            return (0, 0.0)
        return (1, e["rate_value"] if e["rate_value"] is not None else 9e9)

    out.sort(key=_key)
    return out


def fetch_competition(
    service_key,
    house_manage_no=None,
    pblanc_no=None,
    per_page=100,
    timeout=15,
):
    """청약접수 경쟁률을 조회해 매칭 항목을 정규화한 dict 로 반환.

    Args:
        service_key: data.go.kr 발급 serviceKey(디코딩된 값 권장). 하드코딩 금지 → 호출측 전달.
        house_manage_no: 주택관리번호(HOUSE_MANAGE_NO). 지정 시 이 값과 일치하는 항목만.
        pblanc_no: 공고번호(PBLANC_NO). 지정 시 이 값과 일치하는 항목만.
        per_page: 페이지당 조회 건수.
        timeout: 요청 타임아웃(초).

    Returns:
        정규화된 dict. 조회 실패/응답이상/매칭 항목 없음이면 None.
        (house_manage_no 도 pblanc_no 도 주어지지 않으면 첫 항목을 반환)
    """
    # 지연 import: 키/패키지 없이도 모듈 import 자체는 성공해야 함.
    try:
        import requests
    except ImportError:
        return None

    if not service_key:
        return None

    params = {
        "page": 1,
        "perPage": per_page,
        "serviceKey": service_key,
        "returnType": "JSON",
    }
    # 서버 측 필터가 지원되면 트래픽을 줄여주고, 미지원이면 무시된다.
    if house_manage_no:
        params["cond[HOUSE_MANAGE_NO::EQ]"] = str(house_manage_no)
    if pblanc_no:
        params["cond[PBLANC_NO::EQ]"] = str(pblanc_no)

    try:
        r = requests.get(API_URL, params=params, timeout=timeout)
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError):
        # 네트워크 오류 / 타임아웃 / JSON 파싱 실패 등 → 조용히 None.
        return None
    except Exception:
        # 방어적: 예기치 못한 예외에도 파이프라인이 죽지 않도록.
        return None

    data = body.get("data", []) or []
    if not data:
        return None

    hmn = str(house_manage_no) if house_manage_no is not None else None
    pno = str(pblanc_no) if pblanc_no is not None else None

    matched = None
    for it in data:
        if not isinstance(it, dict):
            continue
        if hmn is not None and str(it.get("HOUSE_MANAGE_NO", "") or "") != hmn:
            continue
        if pno is not None and str(it.get("PBLANC_NO", "") or "") != pno:
            continue
        matched = it
        break

    # 식별자를 하나도 안 줬으면 첫 유효 항목을 사용.
    if matched is None and hmn is None and pno is None:
        for it in data:
            if isinstance(it, dict):
                matched = it
                break

    if matched is None:
        return None

    return _norm(matched)
