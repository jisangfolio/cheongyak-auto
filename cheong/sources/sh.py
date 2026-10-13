"""SH(서울주택도시공사) 공고 — 서울주거포털 목록을 읽는다.

SH는 공식 공고 API가 없다. 서울주거포털(housing.seoul.go.kr)이 SH 공고를
표로 정리해 주므로 그걸 파싱한다. 열 순서가 페이지마다 달라 '열 이름'으로 매핑한다.
  임대: 번호 | 청약유형 | 공고명 | 공고게시일 | 발표일 | 모집상태 | 담당부서 | 링크
  분양: 번호 | 청약유형 | 공고명 | 공고게시일 | 발표일 | 담당부서 | 링크
목록에는 접수기간이 없다(공고문 안에 있음) → 게시일·발표일·상태만 쓴다.

서울주거포털에 안 올라오는 공고(사회주택 등)가 있어서 SH 홈페이지 '공고 및 공지'
게시판(i-sh.co.kr m_241)의 주택임대·주택분양 분류도 읽는다. 글번호(seq)가 포털과 같아
겹치는 건 포털 쪽을 쓰고, 홈페이지에만 있는 '모집' 공고를 더한다.
  POST list.do  page=N & multi_itm_seq=2(주택임대) / 1(주택분양)
  표: 번호 | 제목(onclick getDetailView('seq')) | 담당부서 | 등록일 | 조회수
"""
import re

from bs4 import BeautifulSoup

from ..models import Notice
from ..util import get, parse_date, post

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


BOARD = "https://www.i-sh.co.kr/main/lay2/program/S1T294C295/www/brd/m_241/"
BOARD_KINDS = {"2": "주택임대", "1": "주택분양"}
# 모집 공고가 아닌 후속 안내(발표·계약·점검 등)는 뺀다
_SKIP = ("발표", "결과", "계약", "사전점검", "주택공개", "안내문", "등기", "동호", "서류제출")


def parse_board(html, kind):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.find_all("table"):
        heads = [th.get_text(strip=True) for th in table.select("thead th")]
        if "제목" not in heads or "등록일" not in heads:
            continue
        ti, di = heads.index("제목"), heads.index("등록일")
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            a = tr.find("a", onclick=True)
            m = re.search(r"getDetailView\('(\d+)'\)", a["onclick"]) if a else None
            if not m or len(tds) <= max(ti, di):
                continue
            for sp in tds[ti].select(".icoNew"):
                sp.decompose()
            title = tds[ti].get_text(" ", strip=True)
            if "모집" not in title or any(k in title for k in _SKIP):
                continue
            out.append(Notice(
                source="SH", uid=m.group(1), title=title,
                category=BOARD_KINDS.get(kind, ""), region="서울",
                posted=parse_date(tds[di].get_text()),
                url=f"{BOARD}view.do?seq={m.group(1)}",
                extra={"board": "i-sh", "dept": tds[2].get_text(strip=True) if len(tds) > 2 else ""},
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
    for kind in BOARD_KINDS:                              # SH 홈페이지 게시판 (포털에 없는 공고)
        for page in range(1, pages + 1):
            try:
                html = post(BOARD + "list.do", {"page": page, "multi_itm_seq": kind}, label="SH홈").text
            except Exception as e:  # noqa: BLE001
                print(f"[SH홈] {BOARD_KINDS[kind]} p{page} 실패: {e}")
                break
            for n in parse_board(html, kind):
                if n.uid not in seen:
                    seen.add(n.uid)
                    out.append(n)
    return out
