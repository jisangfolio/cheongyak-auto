"""서울시 사회주택 플랫폼의 입주 가능 주택 목록."""
from urllib.parse import urlencode

from ..models import Notice
from ..util import get

BASE = "https://soco.seoul.go.kr/soHouse/pgm/home/sohome/"


def to_notice(row):
    uid = str(row.get("homeCode") or "").strip()
    title = (row.get("homeName") or "").strip()
    try:
        vacant = int(row.get("statusCnt") or 0)
    except (TypeError, ValueError):
        return None
    if not (uid and title and vacant > 0):
        return None

    query = urlencode({"menuNo": "300006", "homeCode": uid})
    return Notice(
        source="사회주택",
        uid=uid,
        title=title.removeprefix("[사회주택]").strip(),
        category="사회주택 공실",
        region="서울",
        address=(row.get("adres") or row.get("adresGu") or "").strip(),
        households=str(vacant),
        url=f"{BASE}view.do?{query}",
        status="공실 있음",
    )


def fetch(cfg, today):  # noqa: ARG001
    # 공식 목록의 '입주 가능' 필터. maxpage는 공실 없는 주택도 세므로 빈 페이지에서 멈춘다.
    page = 1
    notices = {}
    while True:
        body = get(f"{BASE}soHomeListJson.json", {"pageNum": page, "rowCount": 30, "searchSil": "Y"},
                   timeout=10, label="서울 사회주택").json()
        rows = body["resultList"]
        if not isinstance(rows, list):
            raise ValueError("서울 사회주택 목록 응답 형식 변경")
        for row in rows:
            notice = to_notice(row)
            if notice:
                notices.setdefault(notice.uid, notice)
        if not rows or page >= int(body["maxpage"]):
            return list(notices.values())
        page += 1
