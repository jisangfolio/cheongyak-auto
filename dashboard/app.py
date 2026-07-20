"""청약 공고 Streamlit 대시보드 (cheong.db 에서 읽는다).

프로젝트 루트에서 실행한다:
    streamlit run dashboard/app.py

화면 구성
  (1) 사이드바: 관심지역 필터 입력 + "진행중만" 체크
  (2) 본문: db.get_notices 로 공고 표(주택명/지역/유형/청약접수/당첨발표/공급세대/링크)
  (3) 사이드바: 청약가점 계산기(무주택기간/부양가족/통장기간 → gajeom.calc_gajeom)
  (4) 데이터가 없으면 apt-watch 를 먼저 실행하라고 안내

대시보드 전용 파일이므로 streamlit 은 파일 상단에서 import 한다.
단, cheong 패키지는 sys.path 보정 후 import 하며, DB 미존재/빈 DB 를 방어한다.
"""
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

# 프로젝트 루트(dashboard/의 부모)를 sys.path 에 추가해 cheong 패키지를 import.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from cheong import db, gajeom  # noqa: E402  (sys.path 보정 이후 import)


def _parse_date(s):
    """날짜 문자열을 date로 파싱한다(applyhome.py·db.py와 동일 포맷).

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


def _fmt_date(s):
    """표시용 날짜 문자열(YYYY-MM-DD). 파싱 실패 시 원본을 그대로 돌려준다."""
    d = _parse_date(s)
    if d is None:
        return str(s or "")
    return d.isoformat()


def _load_notices(regions, active_only):
    """db.get_notices 를 호출하되 DB 미존재/오류를 방어한다.

    반환: (notices, error)
      · notices: dict 리스트(성공 시). 실패하면 빈 리스트.
      · error  : 오류 메시지 문자열 또는 None.
    """
    try:
        notices = db.get_notices(regions=regions or None, active_only=active_only)
        return notices, None
    except Exception as exc:  # noqa: BLE001  (DB 파일 없음·스키마 오류 등 광범위 방어)
        # DB 파일이 없거나 손상된 경우에도 대시보드가 죽지 않게 방어한다.
        return [], str(exc)


def _to_table_rows(notices):
    """공고 dict 리스트를 표시용 행 리스트로 변환한다.

    컬럼: 주택명/지역/유형/청약접수/당첨발표/공급세대/링크.
    개별 레코드 오류는 건너뛰어 표 전체가 깨지지 않게 한다.
    """
    rows = []
    for rec in notices:
        try:
            begin = _fmt_date(rec.get("begin"))
            end = _fmt_date(rec.get("end"))
            if begin and end:
                receipt = f"{begin} ~ {end}"
            else:
                receipt = begin or end or ""
            rows.append(
                {
                    "주택명": rec.get("name", "") or "",
                    "지역": rec.get("area", "") or "",
                    "유형": rec.get("type", "") or "",
                    "청약접수": receipt,
                    "당첨발표": _fmt_date(rec.get("award")),
                    "공급세대": rec.get("households", "") or "",
                    "링크": rec.get("url", "") or "",
                }
            )
        except (AttributeError, TypeError):
            # 형태가 어긋난 레코드는 조용히 건너뛴다(방어적).
            continue
    return rows


def _render_notice_table(rows):
    """공고 표를 렌더링한다. 링크 컬럼은 클릭 가능하게 시도한다."""
    # st.column_config 는 신버전 전용이므로 없으면 일반 표로 폴백한다.
    try:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "링크": st.column_config.LinkColumn("링크", display_text="바로가기"),
            },
        )
    except Exception:  # noqa: BLE001  (구버전 streamlit·column_config 미지원 방어)
        st.table(rows)


def _render_gajeom_sidebar():
    """사이드바 청약가점 계산기를 렌더링한다."""
    st.sidebar.header("청약가점 계산기")
    st.sidebar.caption("84점 만점 · 참고용(실제 자격판정은 청약홈에서 확인)")

    no_house = st.sidebar.number_input(
        "무주택기간(년)", min_value=0.0, max_value=30.0, value=0.0, step=0.5,
    )
    dependents = st.sidebar.number_input(
        "부양가족수(명)", min_value=0, max_value=10, value=0, step=1,
    )
    account = st.sidebar.number_input(
        "청약통장 가입기간(년)", min_value=0.0, max_value=30.0, value=0.0, step=0.5,
    )

    try:
        result = gajeom.calc_gajeom(no_house, dependents, account)
    except Exception as exc:  # noqa: BLE001  (계산기 오류가 대시보드를 죽이지 않게)
        st.sidebar.error(f"가점 계산 오류: {exc}")
        return

    st.sidebar.metric("총점", f"{result['total']} / {result['max']}")

    breakdown = result.get("breakdown", {})
    detail = result.get("detail", {})
    col1, col2, col3 = st.sidebar.columns(3)
    col1.metric("무주택", breakdown.get("no_house", 0))
    col2.metric("부양가족", breakdown.get("dependents", 0))
    col3.metric("통장", breakdown.get("account", 0))

    # 세부 산정 근거는 접어서 보여준다.
    with st.sidebar.expander("산정 근거 보기"):
        st.write(detail.get("no_house", ""))
        st.write(detail.get("dependents", ""))
        st.write(detail.get("account", ""))


def _render_region_sidebar():
    """사이드바 관심지역 필터·진행중 체크를 렌더링한다.

    반환: (regions, active_only)
      · regions   : 공백/쉼표로 구분된 관심지역 문자열 리스트.
      · active_only: "진행중만" 체크 여부.
    """
    st.sidebar.header("공고 필터")
    raw = st.sidebar.text_input(
        "관심지역(쉼표로 구분)",
        value="",
        placeholder="예: 서울, 경기",
        help="입력한 지역명이 공고 지역에 포함되면 표시합니다.",
    )
    active_only = st.sidebar.checkbox("진행중만", value=True)

    # 쉼표·공백으로 나눠 빈 항목을 제거한다.
    regions = []
    for part in str(raw).replace("\n", ",").split(","):
        part = part.strip()
        if part:
            regions.append(part)
    return regions, active_only


def main():
    """대시보드 진입점."""
    st.set_page_config(page_title="청약 공고 대시보드", page_icon="🏠", layout="wide")
    st.title("🏠 청약 공고 대시보드")
    st.caption(f"기준일: {date.today().isoformat()} · 데이터 출처: cheong.db(로컬 SQLite)")

    # --- 사이드바: 필터 + 가점 계산기 ---
    regions, active_only = _render_region_sidebar()
    st.sidebar.divider()
    _render_gajeom_sidebar()

    # --- 본문: 공고 표 ---
    notices, error = _load_notices(regions, active_only)

    if error is not None:
        # DB 접근 자체가 실패한 경우(파일 없음·손상 등).
        st.warning(
            "데이터베이스를 읽을 수 없습니다. "
            "`python -m cheong.main apt-watch` 를 먼저 실행하세요."
        )
        with st.expander("자세한 오류"):
            st.code(error)
        return

    if not notices:
        # DB는 있으나 공고가 비어 있는 경우.
        st.info(
            "표시할 공고가 없습니다. "
            "`python -m cheong.main apt-watch` 를 먼저 실행하세요."
        )
        if regions or active_only:
            st.caption("필터(관심지역/진행중만) 때문에 결과가 비었을 수도 있습니다.")
        return

    st.subheader(f"공고 {len(notices)}건")
    rows = _to_table_rows(notices)
    if not rows:
        st.info("표시 가능한 공고가 없습니다.")
        return
    _render_notice_table(rows)


# streamlit run 으로 실행하면 스크립트 본문이 top-level 로 평가된다.
if __name__ == "__main__":
    main()
else:
    # streamlit 은 모듈을 __main__ 이 아닌 이름으로 실행할 수 있어 방어적으로 호출.
    main()
