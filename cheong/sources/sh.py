"""SH(서울주택도시공사) 공고 — 서울주거포털 목록을 읽는다.

SH는 공식 공고 API가 없다. 서울주거포털(housing.seoul.go.kr)이 SH 공고를
표로 정리해 주므로 그걸 파싱한다. 열 순서가 페이지마다 달라 '열 이름'으로 매핑한다.
  임대: 번호 | 청약유형 | 공고명 | 공고게시일 | 발표일 | 모집상태 | 담당부서 | 링크
  분양: 번호 | 청약유형 | 공고명 | 공고게시일 | 발표일 | 담당부서 | 링크
목록에는 접수기간이 없다(공고문 안에 있음) → 게시일·발표일·상태만 쓴다.
"""
import re

from bs4 import BeautifulSoup

from ..models import Notice
from ..util import get, parse_date

PAGES = {
    "publicLease": "https://housing.seoul.go.kr/site/main/sh/publicLease/list",
    "publicSale": "https://housing.seoul.go.kr/site/main/sh/publicSale/list",
}
COLS = {"청약유형": "category", "공고명": "title", "공고게시일": "posted",
        "발표일": "announce", "모집상태": "status"}


def parse_list(html, board):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".board-list table")
    if table is None:
        return []
    heads = [th.get_text(strip=True) for th in table.select("thead th")]
    out = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < len(heads):
            continue
        row = {COLS[h]: tds[i].get_text(" ", strip=True) for i, h in enumerate(heads) if h in COLS}
        a = tr.select_one('a[href*="seq="]')
        url = a["href"] if a else ""
        m = re.search(r"seq=(\d+)", url)
        uid = m.group(1) if m else f"{board}:{row.get('title', '')}"
        out.append(Notice(
            source="SH", uid=uid, title=row.get("title", ""),
            category=row.get("category", ""), region="서울",
            posted=parse_date(row.get("posted")), announce=parse_date(row.get("announce")),
            status=row.get("status", ""), url=url,
            extra={"board": board},
        ))
    return out


def fetch(cfg, today):  # noqa: ARG001
    pages = int(cfg["sources"]["sh"].get("pages", 2))
    out, seen = [], set()
    for board, url in PAGES.items():
        for cp in range(1, pages + 1):
            try:
                html = get(url, {"cp": cp, "supplyType": board}, label="SH").text
            except Exception as e:  # noqa: BLE001
                print(f"[SH] {board} p{cp} 실패: {e}")
                break
            rows = parse_list(html, board)
            for n in rows:
                if n.uid not in seen:
                    seen.add(n.uid)
                    out.append(n)
            if not rows:
                break
    return out
