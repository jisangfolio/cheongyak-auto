"""청약 알리미 웹 대시보드 (Streamlit).

터미널 없이 클릭으로:
- 지원가치 있는 공고 보기(청약홈 분양 + LH 임대, 자격 필터)
- '신청 완료' 표시(당첨발표일 첨부) / 해제
- 신청 완료 목록 + 발표·마감 D-day
- 내 자격 사전체크 + 청약가점

실행: 프로젝트 루트에서  streamlit run dashboard/app.py
"""
import os
import sys
from datetime import date

import streamlit as st

# 프로젝트 루트를 import 경로에 추가(cheong 패키지 사용).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cheong import applicability as ap, db, eligibility  # noqa: E402
from cheong.config import load_config  # noqa: E402

st.set_page_config(page_title="청약 알리미", page_icon="🏠", layout="wide")


def _load_cfg():
    try:
        return load_config(os.path.join(_ROOT, "config.yaml"))
    except FileNotFoundError:
        st.error("config.yaml 이 없습니다. config.example.yaml 을 복사해 값을 채우세요.")
        st.stop()


def _refresh(cfg):
    """청약홈 + LH 공고를 다시 받아 DB에 저장. 저장 건수 반환."""
    from cheong.applyhome import _fetch_all, _record
    ah = cfg.get("applyhome", {})
    regions = ah.get("regions") or []
    recs = []
    for it in _fetch_all(ah["service_key"], int(ah.get("per_page", 500))):
        r = _record(it)
        if not regions or any(rg in r["area"] for rg in regions):
            recs.append(r)
    if (cfg.get("lh") or {}).get("enabled"):
        from cheong import lh
        recs += lh.fetch_records(cfg)
    db.init_db()
    return db.upsert_notices(recs)


def _dday(d):
    n = (d - date.today()).days
    return "D-day" if n == 0 else (f"D-{n}" if n > 0 else f"D+{-n}")


cfg = _load_cfg()
청약 = cfg.get("청약", {}) or {}
regions = (cfg.get("applyhome", {}) or {}).get("regions") or []

st.title("🏠 청약 알리미")

# ───────── 사이드바: 내 정보 ─────────
with st.sidebar:
    st.header("내 정보")
    try:
        g = eligibility.gajeom(청약)
        st.metric("예상 청약가점", f"{g['total']} / 84")
        b = g["breakdown"]
        st.caption(f"무주택 {b['no_house']} · 부양 {b['dependents']} · 통장 {b['account']}")
    except Exception as e:  # noqa: BLE001
        st.caption(f"가점 계산 불가: {e}")
    st.caption(f"관심지역: {', '.join(regions) or '(미설정)'}")
    st.divider()
    if st.button("🔄 공고 새로고침 (청약홈+LH)", use_container_width=True):
        with st.spinner("청약홈·LH 공고 불러오는 중..."):
            try:
                n = _refresh(cfg)
                st.success(f"{n}건 갱신 완료")
            except Exception as e:  # noqa: BLE001
                st.error(f"갱신 실패: {e}")
    st.caption("값 수정은 config.yaml 의 '청약' 항목")

tab1, tab2, tab3 = st.tabs(["📋 지원가치 공고", "✅ 신청 완료", "🧮 자격 체크"])

# ───────── 탭1: 지원가치 공고 ─────────
with tab1:
    active = db.get_notices(regions=regions, active_only=True)
    applied = set(db.get_applied())
    worth = [r for r in active
             if str(r["pno"]) not in applied and ap.applicability(r, 청약)["worth"]]
    if not active:
        st.info("공고가 없습니다. 사이드바의 '🔄 공고 새로고침'을 눌러 불러오세요.")
    st.subheader(f"지원가치 있는 공고 {len(worth)}건")
    for r in worth:
        v = ap.applicability(r, 청약)
        with st.container(border=True):
            src = "LH 임대" if r.get("source") == "LH" else "청약홈 분양"
            st.markdown(f"**[{r.get('type', '')}] {r.get('name', '')}**  \n"
                        f":gray[{src} · {r.get('area', '')}]")
            접수 = f"{r.get('begin') or '?'} ~ {r.get('end') or '?'}"
            link = r.get("url", "")
            st.caption(f"청약접수: {접수}"
                       + (f"  ·  [📄 공고 보기]({link})" if link else ""))
            st.write("▸ 지원경로: " + " / ".join(v["paths"]))
            if v.get("note"):
                st.caption("▸ " + v["note"])
            c1, c2 = st.columns([3, 1])
            aw = c1.text_input("당첨발표일 YYYY-MM-DD (선택 — 공고문 확인)",
                               key=f"aw_{r['pno']}", value=r.get("award") or "",
                               placeholder="예: 2026-11-03")
            if c2.button("✅ 신청완료", key=f"done_{r['pno']}", use_container_width=True):
                db.mark_applied(r["pno"], award_date=aw or None)
                st.rerun()

# ───────── 탭2: 신청 완료 ─────────
with tab2:
    applied = db.get_applied()
    notices = {str(n["pno"]): n for n in db.get_notices()}
    today = date.today()
    shown = 0
    for pno, aw in applied.items():
        rec = notices.get(str(pno), {})
        award = db._parse_date(aw) or db._parse_date(rec.get("award"))
        end = db._parse_date(rec.get("end"))
        ref = award or end
        if ref is not None and ref < today:
            continue  # 발표/마감 지남
        shown += 1
        with st.container(border=True):
            st.markdown(f"**[{rec.get('type', '')}] {rec.get('name', pno)}**")
            if award:
                st.caption(f"🏆 당첨발표 {award} · {_dday(award)}")
            elif end:
                st.caption(f"⏰ 마감 {end} · {_dday(end)}")
            else:
                st.caption("신청 완료 (일정 정보 없음)")
            if st.button("취소", key=f"undo_{pno}"):
                db.unmark_applied(pno)
                st.rerun()
    if shown == 0:
        st.info("신청 완료로 표시된 공고가 없습니다. "
                "'📋 지원가치 공고'에서 신청한 공고의 [✅ 신청완료]를 누르세요.")

# ───────── 탭3: 자격 체크 ─────────
with tab3:
    try:
        result = eligibility.check_eligibility(청약)
        gg = result["가점"]
        st.subheader(f"예상 청약가점 {gg['total']} / 84")
        st.write("**특별공급 스크리닝**")
        icon = {"해당가능": "✅", "확인필요": "🟡", "불가": "⛔"}
        for s in result["특별공급"]:
            st.write(f"{icon.get(s['판정'], '·')} **{s['유형']}** — {s['판정']} · {s['근거']}")
        st.write("**일반공급**")
        st.caption(result["일반공급"]["가점"])
        st.caption(f"지역: {result['지역']['거주지']} 거주 {result['지역']['거주기간']} "
                   f"→ {result['지역']['해당지역우선']}")
        st.caption("⚠️ " + result["caveat"])
    except Exception as e:  # noqa: BLE001
        st.error(f"자격 체크 불가: {e} (config.yaml 의 '청약' 값 확인)")
