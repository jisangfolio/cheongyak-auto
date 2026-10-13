"""청약홈(한국부동산원) 분양정보 오픈API.

공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스'(15098547) 활용신청 후
일반 인증키(Decoding)를 APPLYHOME_KEY 로 넣는다.

엔드포인트(같은 키로 모두 호출):
  APT        getAPTLttotPblancDetail           민영·국민(공공) APT 분양
  무순위      getRemndrLttotPblancDetail        무순위·잔여세대(줍줍)
  오피스텔등   getUrbtyOfctlLttotPblancDetail    오피스텔·도시형생활주택·민간임대
  공공지원임대 getPblPvtRentLttotPblancDetail    공공지원 민간임대
"""
from datetime import timedelta

from ..models import Notice
from ..util import get, parse_date, to_sido

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
KINDS = {
    "apt": ("getAPTLttotPblancDetail", "APT"),
    "remndr": ("getRemndrLttotPblancDetail", "무순위/잔여"),
    "urbty": ("getUrbtyOfctlLttotPblancDetail", "오피스텔/도시형/민간임대"),
    "pvtrent": ("getPblPvtRentLttotPblancDetail", "공공지원민간임대"),
}


def _first(it, *keys):
    for k in keys:
        v = it.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def to_notice(it, kind_label):
    addr = _first(it, "HSSPLY_ADRES")
    region = _first(it, "SUBSCRPT_AREA_CODE_NM") or to_sido(addr)
    dtl = _first(it, "HOUSE_DTL_SECD_NM", "SEARCH_HOUSE_SECD_NM")
    secd = _first(it, "HOUSE_SECD_NM")
    category = " ".join(x for x in (kind_label if kind_label != "APT" else "APT", dtl or secd) if x)
    uid = _first(it, "PBLANC_NO", "HOUSE_MANAGE_NO")
    return Notice(
        source="청약홈",
        uid=f"{kind_label}:{uid}",
        title=_first(it, "HOUSE_NM"),
        category=category,
        region=to_sido(region) or region,
        address=addr,
        posted=parse_date(_first(it, "RCRIT_PBLANC_DE")),
        begin=parse_date(_first(it, "RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE", "GNRL_RNK1_CRSPAREA_RCPTDE")),
        end=parse_date(_first(it, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE", "GNRL_RNK2_ETC_AREA_ENDDE")),
        announce=parse_date(_first(it, "PRZWNER_PRESNATN_DE")),
        households=_first(it, "TOT_SUPLY_HSHLDCO", "SUPLY_HSHLDCO"),
        url=_first(it, "PBLANC_URL", "HMPG_ADRES"),
    )


def _fetch_kind(op, key, since, per_page=300, max_pages=10):
    url = BASE + op
    items, page = [], 1
    use_cond = True
    while page <= max_pages:
        params = {"page": page, "perPage": per_page, "serviceKey": key, "returnType": "JSON"}
        if use_cond:
            params["cond[RCRIT_PBLANC_DE::GTE]"] = since.isoformat()
        try:
            body = get(url, params, label=f"청약홈:{op}").json()
        except Exception:
            if use_cond and page == 1:      # 조건 파라미터를 거부하면 조건 없이 재시도
                use_cond = False
                continue
            raise
        data = body.get("data") or []
        items.extend(data)
        if not data or page * per_page >= int(body.get("totalCount") or 0):
            break
        page += 1
    return items


def fetch(cfg, today):
    key = cfg["keys"].get("applyhome")
    if not key:
        print("[청약홈] APPLYHOME_KEY 없음 → 건너뜀")
        return []
    kinds = cfg["sources"]["applyhome"].get("kinds", list(KINDS))
    since = today - timedelta(days=int(cfg["sources"]["applyhome"].get("lookback_days", 60)))
    out = []
    for k in kinds:
        op, label = KINDS[k]
        try:
            for it in _fetch_kind(op, key, since):
                n = to_notice(it, label)
                if n.uid.split(":", 1)[1]:
                    out.append(n)
        except Exception as e:  # noqa: BLE001 - 한 엔드포인트 실패가 전체를 죽이지 않게
            print(f"[청약홈] {label} 조회 실패: {e}")
    return out
