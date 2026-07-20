"""청약홈 청약접수 경쟁률 오픈API 클라이언트 (공공데이터포털 서비스 15098905).

- 특정 공고(주택관리번호/공고번호)의 청약 경쟁률을 조회해 정규화된 dict 로 반환한다.
- 실제 청약 신청은 자동화 대상이 아니며, 여기서는 참고용 경쟁률 정보만 가져온다.

⚠️ 이 서비스(15098905)는 분양정보 서비스(15098547)와 **별도**로
   data.go.kr 에서 활용신청(serviceKey 발급)이 필요하다. 두 서비스의 키는 서로 다르다.
⚠️ REST operation 경로(아래 API_URL)는 공식 명세가 다운로드 .docx 로만 제공되어
   웹에서 문자열로 검증하지 못했다 → **엔드포인트 미검증(가능성) 상태**이며,
   자매 서비스(15098547)의 REB 네이밍 규칙
   (ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail)에 맞춰 가장 유력한
   경로를 사용했다. 운영 중 404/응답이상이면 data.go.kr Swagger UI 의 실제
   operation 명(getAPTLttotPblanc... 계열)으로 API_URL 을 교체할 것.
"""
from datetime import datetime

# 이 서비스는 15098547(분양정보)과 별도 활용신청 필요. 엔드포인트 미검증 가능성 있음.
# 가장 유력한 REST operation 경로(REB 네이밍 규칙 기반, 미검증):
API_URL = (
    "https://api.odcloud.kr/api/ApplyhomeCompetitionRateSvc/v1"
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
        # 지역/순위 등 부가 정보(있으면)
        "region": it.get("SUBSCRPT_AREA_CODE_NM", "") or "",
        "rank": it.get("RANK_NM", "") or it.get("RESIDE_SECD_NM", "") or "",
        # 참고 날짜
        "rcept_ende": it.get("RCEPT_ENDDE", "") or "",
    }


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
