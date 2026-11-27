"""서울시 사회주택 플랫폼의 독립형 공실 목록."""
import re
from urllib.parse import urlencode

from ..models import Notice
from ..util import get

BASE = "https://soco.seoul.go.kr/soHouse/pgm/home/sohome/"
_UNIT_TYPES = {"원룸(오픈형)", "원룸(분리형)", "투룸", "쓰리룸"}
_SHARED = re.compile(r"(?:셰어|쉐어|쉐이)\s*하우스|고시원|(?:공용|공동)\s*(?:주방|부엌|욕실|화장실)")
_PRIVATE_KITCHEN = re.compile(r"(?:개별|전용|독립)\s*(?:주방|부엌)")
_PRIVATE_BATH = re.compile(r"(?:개별|전용|독립)\s*(?:욕실|화장실)")
_IN_UNIT = re.compile(
    r"(?:(?:욕실|화장실)\s*(?:,|및|과|와)\s*(?:주방|부엌)|(?:주방|부엌)\s*(?:,|및|과|와)\s*(?:욕실|화장실))"
    r"(?:\s*시설)?(?:이|가)?\s*(?:포함된|있는|갖춘)[^.!?\n]{0,35}(?:원룸|투룸|쓰리룸)"
)


def to_notice(row):
    uid = str(row.get("homeCode") or "").strip()
    title = (row.get("homeName") or "").strip()
    unit_type = (row.get("houseType") or "").strip()
    detail = row.get("homeDetail") or ""
    try:
        vacant = int(row.get("statusCnt") or 0)
    except (TypeError, ValueError):
        return None
    if not (uid and title and vacant > 0):
        return None
    if unit_type not in _UNIT_TYPES or _SHARED.search(f"{title} {detail}"):
        return None
    if not (_IN_UNIT.search(detail) or (_PRIVATE_KITCHEN.search(detail) and _PRIVATE_BATH.search(detail))):
        return None

    query = urlencode({"menuNo": "300006", "homeCode": uid})
    return Notice(
        source="사회주택",
        uid=uid,
        title=title.removeprefix("[사회주택]").strip(),
        category=f"사회주택 공실 · {unit_type}",
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
