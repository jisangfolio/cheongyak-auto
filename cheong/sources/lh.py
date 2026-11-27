"""LH 분양임대공고문 API (공공데이터포털 15058530 목록 + 15057999 상세).

- 목록: 공고명·지역·유형·게시일·마감일·URL
- 상세: 접수시작·당첨발표일·주소 (마감 전 공고만 보강)
- UPP_AIS_TP_CD: 05 분양주택, 06 임대주택, 13 주거복지(매입임대·전세임대·든든전세), 39 신혼희망타운
  기본은 06·13 (분양·신혼희망타운은 청약홈이 커버)
같은 data.go.kr 키를 쓰되 서비스별로 '활용신청'은 각각 해야 한다.
"""
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from requests import RequestException

from ..models import Notice
from ..util import get, parse_date, to_sido

LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
DTL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"
SEOUL_ROOT = "https://housing.seoul.go.kr/site/main/lh/"
SEOUL_LIST = SEOUL_ROOT + "publicLease/list"
SEOUL_SALE_LISTS = {
    "05": SEOUL_ROOT + "publicSale/05/list",
    "39": SEOUL_ROOT + "publicSale/39/list",
}
_CORRECTION = "[정정공고]"


def _without_superseded(notices):
    corrected = {(n.region, n.category, n.title.removeprefix(_CORRECTION).strip())
                 for n in notices if n.title.startswith(_CORRECTION)}
    return [n for n in notices if n.title.startswith(_CORRECTION)
            or (n.region, n.category, n.title) not in corrected or n.status != "정정공고중"]


def _seoul_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".board-list table")
    heads = [th.get_text(" ", strip=True) for th in table.select("thead th")] if table else []
    columns = ("공고 세부유형명", "공고명", "지역", "공고게시일", "마감일", "상태", "링크")
    if not all(key in heads for key in columns):
        raise ValueError("서울주거포털 LH 공고 목록 열 확인 필요")
    out = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < len(heads):
            continue
        cell = dict(zip(heads, cells))
        link = cell["링크"].find("a", href=True)
        notice_url = link["href"] if link else ""
        parsed = urlsplit(notice_url)
        uid = parse_qs(parsed.query).get("panId", [""])[0]
        if parsed.hostname != "apply.lh.or.kr" or not uid:
            raise ValueError("서울주거포털 LH 공고 링크 확인 필요")
        fields = {key: cell[key].get_text(" ", strip=True) for key in columns}
        category = fields["공고 세부유형명"]
        if "/publicSale/" in url and "분양" not in category:
            category = f"공공분양 {category}".strip()
        out.append(Notice(source="LH", uid=uid, title=fields["공고명"], category=category,
                          region=to_sido(fields["지역"]), posted=parse_date(fields["공고게시일"]),
                          end=parse_date(fields["마감일"]), status=fields["상태"], url=notice_url))
    pages = {cp for link in soup.select('a[href*="cp="]')
             if urlsplit(link["href"]).path == urlsplit(url).path
             for cp in parse_qs(urlsplit(link["href"]).query).get("cp", [])}
    return out, pages


def _fetch_seoul_board(url, **query):
    notices = {}
    for page in range(1, 31):
        result = get(url, {"cp": page, "cnpCdNm": "서울특별시", "cnpCdNmSearchEtc": "etc", **query},
                     timeout=10, retries=2, label="LH서울").text
        rows, pages = _seoul_page(result, url)
        if page > 1 and not any(n.uid not in notices for n in rows):
            raise ValueError("서울주거포털 LH 공고 페이지가 반복됨")
        notices.update((n.uid, n) for n in rows)
        if str(page + 1) not in pages:
            return notices
    raise ValueError("서울주거포털 LH 공고 페이지 상한 초과")


def fetch_seoul():
    """LH API를 쓸 수 없는 환경에서 서울 공공임대·공공분양 목록을 제공한다."""
    notices = _fetch_seoul_board(SEOUL_LIST, supplyType="publicLease")
    for code, url in SEOUL_SALE_LISTS.items():
        try:
            rows = _fetch_seoul_board(url, supplyType="publicSale", aisTpCd=code)
        except (RequestException, ValueError) as e:
            print(f"[LH서울] 분양 목록 실패(유형 {code}): {e}")
            continue
        for uid, notice in rows.items():
            notices.setdefault(uid, notice)
    return _without_superseded(list(notices.values()))


def _seg(body, name):
    if isinstance(body, list):
        for s in body:
            if isinstance(s, dict) and isinstance(s.get(name), list):
                return s[name]
    return []


def to_notice(it):
    return Notice(
        source="LH",
        uid=str(it.get("PAN_ID", "")),
        title=str(it.get("PAN_NM", "")).strip(),
        category=str(it.get("AIS_TP_CD_NM") or it.get("UPP_AIS_TP_NM") or "").strip(),
        region=to_sido(str(it.get("CNP_CD_NM", ""))),
        posted=parse_date(it.get("PAN_NT_ST_DT") or it.get("PAN_DT")),
        end=parse_date(it.get("CLSG_DT")),
        url=str(it.get("DTL_URL", "")),
        status=str(it.get("PAN_SS", "")),
        extra={
            "_ccr": str(it.get("CCR_CNNT_SYS_DS_CD") or ""),
            "_spl": str(it.get("SPL_INF_TP_CD") or ""),
            "_upp": str(it.get("UPP_AIS_TP_CD") or ""),
            "_ais": str(it.get("AIS_TP_CD") or ""),
        },
    )


def apply_detail(n, body):
    """상세 응답으로 접수시작·마감·발표·주소를 채운다."""
    scdl = _seg(body, "dsSplScdl")
    sbd = _seg(body, "dsSbd")
    begins = sorted(d for d in (parse_date(r.get("SBSC_ACP_ST_DT")) for r in scdl) if d)
    ends = sorted(d for d in (parse_date(r.get("SBSC_ACP_CLSG_DT")) for r in scdl) if d)
    awards = sorted(d for d in (parse_date(r.get("PZWR_ANC_DT")) for r in scdl) if d)
    if begins:
        n.begin = begins[0]
    if ends:
        n.end = ends[-1]
    if awards:
        n.announce = awards[0]
    if sbd:
        n.address = str(sbd[0].get("LGDN_ADR", "")).strip()
        hh = [str(r.get("HSH_CNT", "")).strip() for r in sbd if str(r.get("HSH_CNT", "")).strip()]
        if hh:
            try:
                n.households = str(sum(int(h) for h in hh))
            except ValueError:
                n.households = hh[0]


def _detail(key, n):
    params = {
        "serviceKey": key, "PAN_ID": n.uid,
        "CCR_CNNT_SYS_DS_CD": n.extra.get("_ccr") or "03",
        "SPL_INF_TP_CD": n.extra.get("_spl", ""),
        "UPP_AIS_TP_CD": n.extra.get("_upp") or "06",
        "AIS_TP_CD": n.extra.get("_ais", ""),
    }
    try:
        apply_detail(n, get(DTL_URL, params, timeout=15, retries=2, label="LH상세").json())
    except Exception as e:  # noqa: BLE001
        print(f"[LH] 상세 실패 {n.uid}: {e}")


def fetch(cfg, today):
    if cfg.get("lh_public_only"):
        return fetch_seoul()
    key = cfg["keys"].get("lh") or cfg["keys"].get("applyhome")
    if not key:
        print("[LH] LH_KEY 없음 → 서울주거포털 목록으로 대체")
        return fetch_seoul()
    scfg = cfg["sources"]["lh"]
    out = []
    fallback_needed = False
    for upp in scfg.get("upp_types", ["06", "13"]):
        page = 1
        while page <= int(scfg.get("max_pages", 5)):
            try:
                body = get(LIST_URL, {"serviceKey": key, "PG_SZ": 100, "PAGE": page,
                                      "UPP_AIS_TP_CD": upp}, label="LH").json()
                if not isinstance(body, list):
                    raise ValueError("LH 목록 응답 형식 확인 필요")
            except Exception as e:  # noqa: BLE001
                print(f"[LH] 목록 실패(유형 {upp}): {e}")
                fallback_needed = True
                break
            rows = _seg(body, "dsList")
            out.extend(to_notice(r) for r in rows if r.get("PAN_ID"))
            total = int((rows[0].get("ALL_CNT") if rows else 0) or 0)
            if not rows or page * 100 >= total:
                break
            page += 1
    # 마감 전 공고만 상세 보강 (호출 수 제한)
    budget = int(scfg.get("detail_limit", 40))
    regions = set(cfg.get("regions") or [])
    for n in out:
        if budget <= 0:
            break
        if (not regions or not n.region or n.region in regions) and (n.end is None or n.end >= today):
            _detail(key, n)
            budget -= 1
    if not out or fallback_needed:
        portal = fetch_seoul()
        known = {n.uid for n in out}
        out.extend(n for n in portal if n.uid not in known)
    return _without_superseded(out)
