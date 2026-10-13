"""서울시 청년안심주택(구 역세권청년주택) 모집공고 게시판.

목록 페이지(list.do)는 빈 표만 주고, 행은 JS가 bbsListJson.json 을 POST 로 불러 채운다.
그래서 JSON 엔드포인트를 직접 읽는다. 필드(페이지 JS 기준):
  boardId 글번호 · nttSj 공고명 · optn1 공고게시일 · optn4 청약신청일 · optn3 담당부서/사업자
  optn2 1=공공 2=민간 · optn5 1=최초 2=추가
청약신청일(optn4)을 접수 시작일로 쓰고, 마감일은 본문(content)의 '청약신청 : A ~ B' 줄에서 읽는다.
JSON 이 실패하면 예전 HTML 표 파싱(parse_list)으로 한 번 더 시도한다.
"""
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Notice
from ..util import get, parse_date, post

LIST_URL = "https://soco.seoul.go.kr/youth/bbs/BMSR00015/list.do"
JSON_URL = "https://soco.seoul.go.kr/youth/pgm/home/yohome/bbsListJson.json"
BBS_ID = "BMSR00015"
_KIND = {"1": "공공", "2": "민간"}
_ROUND = {"1": "최초", "2": "추가"}


_DT = re.compile(r"(?:(20\d{2}|\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def apply_period(content, begin=None):
    """본문의 '청약신청 : ‘26. 10. 11. (일) 09:00 ~ 10. 15. (목) 23:00' → (시작, 마감).

    마감에 연도가 없으면 시작 연도를 쓴다. 이상한 값(마감<시작, 60일 넘게)은 버린다.
    """
    if not content:
        return begin, None
    text = BeautifulSoup(content, "html.parser").get_text("\n")
    for line in text.splitlines():
        if "청약신청" not in line or "페이지" in line or "~" not in line:
            continue
        found = []
        for m in _DT.finditer(line.split(":", 1)[-1] if ":" in line else line):
            yy, mm, dd = m.groups()
            year = (2000 + int(yy)) if yy and len(yy) == 2 else int(yy) if yy else None
            found.append((year, int(mm), int(dd)))
        if len(found) < 2:
            continue
        (y1, m1, d1), (y2, m2, d2) = found[0], found[-1]
        y1 = y1 or (begin.year if begin else None)
        if not y1:
            continue
        y2 = y2 or (y1 + 1 if m2 < m1 else y1)
        try:
            b, e = date(y1, m1, d1), date(y2, m2, d2)
        except ValueError:
            continue
        if b <= e and (e - b).days <= 60:
            return begin or b, e
    return begin, None


def _s(v):
    return "" if v is None else str(v).strip()


def from_json(it):
    """bbsListJson.json 의 resultList 한 건 → Notice. boardId 없으면 None."""
    bid = _s(it.get("boardId"))
    if not bid:
        return None
    begin, end = apply_period(it.get("content"), parse_date(_s(it.get("optn4"))))
    labels = " ".join(x for x in (_KIND.get(_s(it.get("optn2")), ""), _ROUND.get(_s(it.get("optn5")), "")) if x)
    return Notice(
        source="청년안심", uid=bid, title=_s(it.get("nttSj")),
        category=f"청년안심주택 {labels}".strip(), region="서울",
        posted=parse_date(_s(it.get("optn1"))),
        begin=begin, end=end,
        url=urljoin(LIST_URL, f"view.do?optn1={_s(it.get('optn1'))}&boardId={bid}&menuNo=400008"),
        extra={"supplier": _s(it.get("optn3"))},
    )


def parse_json(body):
    rows = (body or {}).get("resultList") or []
    return [n for n in (from_json(it) for it in rows) if n]


def parse_list(html):
    """예전 방식: 서버가 표를 그려 준 HTML (지금은 JS로 채워져 보통 비어 있음)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    heads = [th.get_text(strip=True) for th in table.select("thead th")]
    idx = {h: i for i, h in enumerate(heads)}
    out = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < len(heads) or "공고명" not in idx:
            continue
        a = tds[idx["공고명"]].find("a")
        href = a.get("href", "") if a else ""
        m = re.search(r"boardId=(\d+)", href)
        if not m:
            continue
        labels = " ".join(s.get_text(strip=True) for s in tds[idx.get("구분", 1)].find_all("span"))
        title = tds[idx["공고명"]].get_text(" ", strip=True)
        out.append(Notice(
            source="청년안심", uid=m.group(1), title=title,
            category=f"청년안심주택 {labels}".strip(), region="서울",
            posted=parse_date(tds[idx["공고게시일"]].get_text()) if "공고게시일" in idx else None,
            begin=parse_date(tds[idx["청약신청일"]].get_text()) if "청약신청일" in idx else None,
            url=urljoin(LIST_URL, href.split("&pageIndex")[0]),
            extra={"supplier": tds[-1].get_text(strip=True)},
        ))
    return out


def _page(p):
    try:
        body = post(JSON_URL, {"bbsId": BBS_ID, "pageIndex": p, "searchAdresGu": "",
                               "searchCondition": "", "searchKeyword": "", "optn2": "", "optn5": ""},
                    label="청년안심").json()
        rows = parse_json(body)
        if rows:
            return rows
    except Exception as e:  # noqa: BLE001
        print(f"[청년안심] JSON p{p} 실패: {e} → HTML 로 재시도")
    return parse_list(get(LIST_URL, {"menuNo": "400008", "pageIndex": p}, label="청년안심").text)


def fetch(cfg, today):  # noqa: ARG001
    pages = int(cfg["sources"]["youth"].get("pages", 2))
    out, seen = [], set()
    for p in range(1, pages + 1):
        try:
            rows = _page(p)
        except Exception as e:  # noqa: BLE001
            print(f"[청년안심] p{p} 실패: {e}")
            break
        for n in rows:
            if n.uid not in seen:
                seen.add(n.uid)
                out.append(n)
        if not rows:
            break
    return out
