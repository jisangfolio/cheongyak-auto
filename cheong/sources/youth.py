"""서울시 청년안심주택(구 역세권청년주택) 모집공고 게시판.

목록 열: 번호 | 구분(공공/민간·추가 등 라벨) | 공고명 | 공고게시일 | 청약신청일 | 담당부서/사업자
청약신청일을 접수 시작일로 쓴다(마감일은 공고문 안에 있음).
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Notice
from ..util import get, parse_date

LIST_URL = "https://soco.seoul.go.kr/youth/bbs/BMSR00015/list.do"


def parse_list(html):
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


def fetch(cfg, today):  # noqa: ARG001
    pages = int(cfg["sources"]["youth"].get("pages", 2))
    out = []
    for p in range(1, pages + 1):
        try:
            html = get(LIST_URL, {"menuNo": "400008", "pageIndex": p}, label="청년안심").text
        except Exception as e:  # noqa: BLE001
            print(f"[청년안심] p{p} 실패: {e}")
            break
        rows = parse_list(html)
        out.extend(rows)
        if not rows:
            break
    return out
