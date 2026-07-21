"""SQLite 영속 계층 (표준 sqlite3만 사용).

청약 공고(notices)·확인이력(seen)·경쟁률(competition)을 파일 DB에 저장한다.
- 기존 .seen_pblanc.json 기반 흐름을 DB로 이관하기 위한 계층
- 외부 패키지 의존 없음(표준 라이브러리 sqlite3/json/datetime/pathlib)
커넥션은 함수마다 with 블록으로 열고 닫는다.
"""
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

# 기본 DB 경로: 프로젝트 루트의 data/ 아래(패키지 위치 기준 상대경로).
# 절대경로 하드코딩을 피해 Docker(/app)·CI 러너에서도 이식 가능하게 한다.
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "cheongyak.db"

# notices 테이블에 저장하는 컬럼 순서(record dict 키와 동일).
_NOTICE_FIELDS = (
    "pno", "name", "area", "type", "addr", "households",
    "notice_de", "begin", "end", "award", "url",
)


def _parse_date(s):
    """날짜 문자열을 date로 파싱한다(applyhome.py와 동일 포맷).

    %Y-%m-%d → %Y.%m.%d → %Y%m%d 순으로 시도하고, 실패하면 None.
    """
    if not s:
        return None
    s = str(s).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _connect(db_path):
    """커넥션을 연다. row를 dict처럼 다루기 위해 row_factory 설정."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=DEFAULT_DB):
    """테이블이 없으면 생성한다. 부모 디렉터리도 함께 만든다."""
    db_path = Path(db_path)
    # 부모 디렉터리 생성(이미 있어도 무방).
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                pno TEXT PRIMARY KEY,
                name TEXT,
                area TEXT,
                type TEXT,
                addr TEXT,
                households TEXT,
                notice_de TEXT,
                begin TEXT,
                end TEXT,
                award TEXT,
                url TEXT,
                first_seen_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS seen (pno TEXT PRIMARY KEY)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competition (
                pno TEXT PRIMARY KEY,
                data_json TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS applied (pno TEXT PRIMARY KEY, applied_at TEXT)"
        )
        conn.commit()


def upsert_notices(records, db_path=DEFAULT_DB):
    """공고 레코드를 INSERT OR REPLACE 한다. 처리 건수를 반환.

    - record dict 키: pno, name, area, type, addr, households,
      notice_de, begin, end, award, url
    - 새 pno일 때만 first_seen_at을 현재시각(ISO)으로 채운다.
    - 기존 pno는 first_seen_at을 보존한다.
    - pno가 비어 있으면 건너뛴다.
    """
    init_db(db_path)
    count = 0
    with _connect(db_path) as conn:
        for rec in records:
            try:
                pno = str(rec.get("pno", "") or "").strip()
                if not pno:
                    # pno 없는 레코드는 저장 불가 → 건너뜀.
                    continue

                # 기존 first_seen_at 조회(있으면 보존).
                row = conn.execute(
                    "SELECT first_seen_at FROM notices WHERE pno = ?", (pno,)
                ).fetchone()
                if row is not None and row["first_seen_at"]:
                    first_seen_at = row["first_seen_at"]
                else:
                    first_seen_at = datetime.now().isoformat()

                values = [pno]
                # pno 이외 필드 채우기(빈 값 방어).
                for key in _NOTICE_FIELDS[1:]:
                    val = rec.get(key, "")
                    values.append("" if val is None else str(val))
                values.append(first_seen_at)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO notices
                        (pno, name, area, type, addr, households,
                         notice_de, begin, end, award, url, first_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                count += 1
            except (sqlite3.Error, ValueError, TypeError):
                # 개별 레코드 오류는 무시하고 계속 진행(방어적).
                continue
        conn.commit()
    return count


def get_notices(regions=None, active_only=False, today=None, db_path=DEFAULT_DB):
    """저장된 공고를 dict 리스트로 반환한다.

    - regions: 부분일치 문자열 리스트. 주면 area에 하나라도 포함되는 것만.
    - active_only: True면 end 날짜 >= today 인 것만(end 파싱 실패는 포함).
    - today: 기준일(기본 date.today()).
    - 정렬: begin 기준.
    """
    init_db(db_path)
    if today is None:
        today = date.today()

    results = []
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM notices").fetchall()

    for row in rows:
        rec = dict(row)
        area = rec.get("area") or ""

        # 지역 부분일치 필터.
        if regions:
            if not any(rg in area for rg in regions):
                continue

        # 활성 공고 필터(마감일 >= 오늘). 파싱 실패(None)는 활성으로 간주.
        if active_only:
            end = _parse_date(rec.get("end"))
            if end is not None and end < today:
                continue

        results.append(rec)

    # begin 기준 정렬. 파싱 불가한 값은 뒤로.
    def _begin_key(r):
        d = _parse_date(r.get("begin"))
        return (d is None, d or date.min)

    results.sort(key=_begin_key)
    return results


def mark_seen(pno, db_path=DEFAULT_DB):
    """pno를 seen 테이블에 기록한다(이미 있으면 무시)."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen (pno) VALUES (?)", (pno,)
        )
        conn.commit()


def is_seen(pno, db_path=DEFAULT_DB):
    """pno가 seen 테이블에 있는지 여부를 반환한다."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return False
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen WHERE pno = ?", (pno,)
        ).fetchone()
    return row is not None


def get_seen(db_path=DEFAULT_DB):
    """seen 테이블의 모든 pno를 set으로 반환한다."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT pno FROM seen").fetchall()
    return {row["pno"] for row in rows}


def mark_applied(pno, db_path=DEFAULT_DB):
    """pno를 '신청 완료'로 기록한다(신청한 시각도 저장)."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO applied (pno, applied_at) VALUES (?, ?)",
            (pno, datetime.now().isoformat()),
        )
        conn.commit()


def unmark_applied(pno, db_path=DEFAULT_DB):
    """'신청 완료' 표시를 해제한다."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM applied WHERE pno = ?", (pno,))
        conn.commit()


def is_applied(pno, db_path=DEFAULT_DB):
    """pno가 신청 완료로 표시돼 있는지 여부."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return False
    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM applied WHERE pno = ?", (pno,)).fetchone()
    return row is not None


def get_applied(db_path=DEFAULT_DB):
    """{pno: applied_at} 형태로 신청 완료 목록을 반환한다."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT pno, applied_at FROM applied").fetchall()
    return {row["pno"]: row["applied_at"] for row in rows}


def save_competition(pno, payload, db_path=DEFAULT_DB):
    """경쟁률 payload(dict)를 JSON 문자열로 저장한다(INSERT OR REPLACE)."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return
    try:
        data_json = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        # 직렬화 불가한 값은 문자열화하여 저장(방어적).
        data_json = json.dumps(str(payload), ensure_ascii=False)
    updated_at = datetime.now().isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO competition (pno, data_json, updated_at)
            VALUES (?, ?, ?)
            """,
            (pno, data_json, updated_at),
        )
        conn.commit()


def get_competition(pno, db_path=DEFAULT_DB):
    """저장된 경쟁률 payload(dict)를 반환한다. 없으면 None."""
    init_db(db_path)
    pno = str(pno or "").strip()
    if not pno:
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT data_json FROM competition WHERE pno = ?", (pno,)
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["data_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def migrate_seen_file(seen_json_path, db_path=DEFAULT_DB):
    """기존 JSON(리스트 of pno 문자열)을 seen 테이블로 임포트한다.

    임포트한 건수를 반환. 파일이 없으면 0.
    """
    seen_json_path = Path(seen_json_path)
    if not seen_json_path.exists():
        return 0

    init_db(db_path)
    try:
        raw = seen_json_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        # 파일 읽기/파싱 실패 시 임포트 없음.
        return 0

    if not isinstance(data, list):
        return 0

    count = 0
    with _connect(db_path) as conn:
        for pno in data:
            pno = str(pno or "").strip()
            if not pno:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO seen (pno) VALUES (?)", (pno,)
            )
            count += 1
        conn.commit()
    return count
