"""HUG 안심전세포털의 서울 든든전세 모집 회차."""
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..models import Notice
from ..util import get, parse_date, to_sido

LIST_URL = "https://m.khug.or.kr/jeonse/web/s07/s070102.jsp"
SEOUL = {"CMB_SIDO": "01", "sbGugun": "ALL", "BJAMT": "ALL", "BJAREA": "ALL",
         "BJORDER": "ALL", "cur_page": 1, "view_Count": "Y"}
_DATE = re.compile(r"20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}")


def parse_list(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.d_list")
    if table is None:
        raise ValueError("HUG 든든전세 모집 표를 찾을 수 없습니다")
    columns = {th.get_text(" ", strip=True): i for i, th in enumerate(table.select("thead th"))}
    if not {"공고일자", "청약 접수기간", "시도"} <= columns.keys():
        raise ValueError("HUG 든든전세 모집 표의 열이 변경되었습니다")

    rounds = {}
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < len(columns):
            if "등록된 게시물이 없습니다" in row.get_text(" ", strip=True):
                continue
            raise ValueError("HUG 든든전세 모집 표의 행이 변경되었습니다")
        if to_sido(cells[columns["시도"]].get_text(strip=True)) != "서울":
            continue
        posted = parse_date(cells[columns["공고일자"]].get_text(strip=True))
        period = cells[columns["청약 접수기간"]].get_text(" ", strip=True)
        dates = [parse_date(value) for value in _DATE.findall(period)]
        if posted is None or len(dates) != 2 or None in dates or dates[0] > dates[1]:
            raise ValueError("HUG 든든전세 서울 모집 일정 형식을 확인해 주세요")
        begin, end = dates
        uid = posted.isoformat()
        if uid in rounds:
            notice = rounds[uid]
            notice.begin = min(notice.begin, begin)
            notice.end = max(notice.end, end)
        else:
            rounds[uid] = Notice(
                source="HUG", uid=uid, title=f"서울 든든전세주택 입주자 모집 ({uid})",
                category="든든전세주택", region="서울", posted=posted, begin=begin, end=end,
                url=f"{LIST_URL}?{urlencode(SEOUL)}",
            )
    return list(rounds.values())


def fetch(cfg, today):  # noqa: ARG001
    # 주택별 행이 같은 회차를 반복하므로 서울 첫 페이지에서 모집 회차만 가져온다.
    response = get(LIST_URL, SEOUL, timeout=12, retries=2, label="HUG")
    return parse_list(response.content.decode("cp949"))
