"""python -m unittest -v  (네트워크 없이 고정 데이터로 검증)

fixtures/sh_lease.html : 2026-10-13 서울주거포털 SH 공공임대 목록 실제 HTML 일부
fixtures/youth.html    : 같은 날 청년안심주택 목록 일부 (리마인더 검증용으로 첫 행 청약신청일만 10-14로 바꿈)
fixtures/youth.json    : 같은 목록의 bbsListJson.json 응답 형태 (페이지 JS가 쓰는 필드명 기준)
청약홈·LH 응답은 API 필드명에 맞춰 만든 예시값이다.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cheong import discord
from cheong.eligibility import judge
from cheong.main import evaluate, plan
from cheong.profile import DEFAULT, age
from cheong.sources import applyhome, lh, sh, youth
from cheong.state import State

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 13)
ME = {**DEFAULT, "birth": "2000", "monthly_income": 330, "regions": ["서울"],
      "residence": "서울", "residence_since": "2026-09"}

APT = {"HOUSE_MANAGE_NO": "2026000500", "PBLANC_NO": "2026000500", "HOUSE_NM": "예시 서울 민영 아파트",
       "HOUSE_SECD_NM": "APT", "HOUSE_DTL_SECD_NM": "민영", "SUBSCRPT_AREA_CODE_NM": "서울",
       "HSSPLY_ADRES": "서울특별시 강서구 예시동 1", "TOT_SUPLY_HSHLDCO": 320,
       "RCRIT_PBLANC_DE": "2026-10-10", "RCEPT_BGNDE": "2026-10-14", "RCEPT_ENDDE": "2026-10-16",
       "PRZWNER_PRESNATN_DE": "2026-10-22", "PBLANC_URL": "https://www.applyhome.co.kr/x"}
APT_GG = {**APT, "PBLANC_NO": "2026000501", "HOUSE_NM": "향남역 예시", "SUBSCRPT_AREA_CODE_NM": "경기",
          "HSSPLY_ADRES": "경기도 화성시"}
REMNDR = {"HOUSE_MANAGE_NO": "2026910001", "PBLANC_NO": "2026910001", "HOUSE_NM": "청계 예시 무순위",
          "HOUSE_SECD_NM": "무순위", "HSSPLY_ADRES": "서울특별시 성동구", "SUBSCRPT_RCEPT_BGNDE": "2026-10-19",
          "SUBSCRPT_RCEPT_ENDDE": "2026-10-19", "RCRIT_PBLANC_DE": "2026-10-12"}
LH_LIST = [{"dsSch": [{}]}, {"dsList": [
    {"PAN_ID": "2015122300019001", "PAN_NM": "서울지역본부 26년 2차 비분양전환 든든전세 입주자 모집",
     "CNP_CD_NM": "서울특별시", "AIS_TP_CD_NM": "매입임대", "PAN_NT_ST_DT": "2026.10.06", "CLSG_DT": "2026.10.16",
     "PAN_SS": "접수중", "DTL_URL": "https://apply.lh.or.kr/x", "UPP_AIS_TP_CD": "13", "ALL_CNT": "2"},
    {"PAN_ID": "2015122300019002", "PAN_NM": "의왕청계2 A1블록 신혼희망타운 행복주택 입주자모집",
     "CNP_CD_NM": "경기도", "AIS_TP_CD_NM": "행복주택", "PAN_NT_ST_DT": "2026.09.29", "CLSG_DT": "2026.10.15",
     "PAN_SS": "접수중", "DTL_URL": "https://apply.lh.or.kr/y", "UPP_AIS_TP_CD": "06", "ALL_CNT": "2"},
]}]
LH_DTL = [{"dsSplScdl": [{"SBSC_ACP_ST_DT": "20261014", "SBSC_ACP_CLSG_DT": "20261016", "PZWR_ANC_DT": "20261120"}]},
          {"dsSbd": [{"LGDN_ADR": "서울특별시 일원", "HSH_CNT": "120"}]}]


def sample():
    ns = sh.parse_list((FX / "sh_lease.html").read_text(encoding="utf-8"), "publicLease")
    ns += youth.parse_list((FX / "youth.html").read_text(encoding="utf-8"))
    ns += [applyhome.to_notice(APT, "APT"), applyhome.to_notice(APT_GG, "APT"),
           applyhome.to_notice(REMNDR, "무순위/잔여")]
    lhs = [lh.to_notice(r) for r in LH_LIST[1]["dsList"]]
    lh.apply_detail(lhs[0], LH_DTL)
    return ns + lhs


def by_title(rows, word):
    return next(v for n, v in rows if word in n.title)


class ParserTest(unittest.TestCase):
    def test_sh(self):
        ns = sh.parse_list((FX / "sh_lease.html").read_text(encoding="utf-8"), "publicLease")
        self.assertEqual(len(ns), 7)
        n = ns[0]
        self.assertEqual((n.uid, n.category, n.status, n.posted), ("311349", "수요자맞춤형", "모집중", date(2026, 10, 12)))
        self.assertIn("view.do?seq=311349", n.url)
        self.assertEqual(ns[3].announce, date(2027, 1, 27))

    def test_youth(self):
        ns = youth.parse_list((FX / "youth.html").read_text(encoding="utf-8"))
        self.assertEqual([n.uid for n in ns], ["6695", "6692"])
        self.assertIn("민간", ns[0].category)
        self.assertTrue(ns[0].url.startswith("https://soco.seoul.go.kr/youth/bbs/BMSR00015/view.do?"))

    def test_youth_json(self):
        body = json.loads((FX / "youth.json").read_text(encoding="utf-8"))
        ns = youth.parse_json(body)
        self.assertEqual([n.uid for n in ns], ["6695", "6692"])
        n = ns[0]
        self.assertEqual((n.category, n.posted, n.begin), ("청년안심주택 민간 추가", date(2026, 10, 8), date(2026, 10, 14)))
        self.assertEqual(n.url, "https://soco.seoul.go.kr/youth/bbs/BMSR00015/view.do?optn1=2026-10-08&boardId=6695&menuNo=400008")

    def test_youth_period_from_content(self):
        c = ('<p>■모집공고 : ‘26. 10. 08. (목)</p><p><span><b>■청약신청 : ‘26. 10. 11. (일) 09:00 ~ 10. 15. (목) 23:00</b>'
             '</span></p><p>■ 청약신청 페이지 : https://x.com</p>')
        self.assertEqual(youth.apply_period(c, date(2026, 10, 11)), (date(2026, 10, 11), date(2026, 10, 15)))
        self.assertEqual(youth.apply_period("■청약신청 : 2026.12.29 ~ 2027.01.03", None),
                         (date(2026, 12, 29), date(2027, 1, 3)))
        self.assertEqual(youth.apply_period("■청약신청 : ‘26. 12. 29. ~ 1. 3.", None),
                         (date(2026, 12, 29), date(2027, 1, 3)))
        self.assertEqual(youth.apply_period("<p>내용 없음</p>", date(2026, 10, 9)), (date(2026, 10, 9), None))

    def test_applyhome_kinds_real_fields(self):
        # 2026-10-13 실제 응답에서 확인한 필드 (공공지원민간임대는 YYYYMMDD · HOUSE_DETAIL_SECD_NM)
        p = applyhome.to_notice({"HOUSE_MANAGE_NO": "2026850051", "PBLANC_NO": "2026850051",
                                 "HOUSE_NM": "x", "HOUSE_SECD_NM": "공공지원민간임대",
                                 "HOUSE_DETAIL_SECD_NM": "공공지원민간임대", "SUBSCRPT_AREA_CODE_NM": "부산",
                                 "RCRIT_PBLANC_DE": "20261012", "SUBSCRPT_RCEPT_BGNDE": "20261019",
                                 "SUBSCRPT_RCEPT_ENDDE": "20261020", "PRZWNER_PRESNATN_DE": "20261023"},
                                "공공지원민간임대")
        self.assertEqual((p.region, p.posted, p.begin, p.end, p.announce),
                         ("부산", date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 23)))
        u = applyhome.to_notice({"PBLANC_NO": "2026950077", "HOUSE_NM": "y", "HOUSE_DTL_SECD_NM": "오피스텔",
                                 "SUBSCRPT_AREA_CODE_NM": "경기", "SUBSCRPT_RCEPT_BGNDE": "2026-10-19",
                                 "SUBSCRPT_RCEPT_ENDDE": "2026-10-20"}, "오피스텔/도시형/민간임대")
        self.assertIn("오피스텔", u.category)
        self.assertEqual((u.begin, u.end), (date(2026, 10, 19), date(2026, 10, 20)))

    def test_applyhome_and_lh(self):
        a = applyhome.to_notice(REMNDR, "무순위/잔여")
        self.assertEqual((a.region, a.begin), ("서울", date(2026, 10, 19)))
        x = lh.to_notice(LH_LIST[1]["dsList"][0])
        lh.apply_detail(x, LH_DTL)
        self.assertEqual((x.region, x.begin, x.end, x.households), ("서울", date(2026, 10, 14), date(2026, 10, 16), "120"))


class EligibilityTest(unittest.TestCase):
    def setUp(self):
        self.rows = evaluate(sample(), ME, TODAY)

    def test_age(self):
        self.assertEqual(age(ME, TODAY), 25)

    def test_me(self):
        r = self.rows
        self.assertEqual(by_title(r, "든든전세").level, "추천")
        self.assertEqual(by_title(r, "신독산역").level, "추천")              # 청년안심
        self.assertEqual(by_title(r, "신혼·신생아").level, "제외")
        self.assertEqual(by_title(r, "은빛주택").level, "제외")
        self.assertEqual(by_title(r, "예술인").level, "제외")
        hope = next(n for n in sample() if "희망하우징" in n.title)
        self.assertEqual(judge(hope, ME, TODAY).level, "제외")              # 대학생 대상
        self.assertEqual(by_title(r, "향남역").level, "제외")                # 경기
        self.assertEqual(by_title(r, "의왕청계2").level, "제외")
        self.assertFalse(any("장기전세" in n.title for n, _ in r))  # 8/31 게시 → 21일 지나 종료 처리
        apt = by_title(r, "서울 민영")
        self.assertEqual(apt.level, "확인")
        self.assertTrue(any("가점 0점" in t for t in apt.tips))

    def test_newlywed_profile(self):
        p = {**ME, "marital": "신혼", "newborn": True}
        self.assertEqual(by_title(evaluate(sample(), p, TODAY), "신혼·신생아").level, "추천")

    def test_closed_dropped(self):
        later = [n.title for n, _ in evaluate(sample(), ME, date(2026, 10, 17))]
        self.assertFalse(any("화곡역" in t for t in later))    # 10/9 접수 → 7일 넘으면 종료 처리
        self.assertFalse(any("든든전세" in t for t in later))  # 10/16 마감 지남


class PlanTest(unittest.TestCase):
    def test_first_then_reminder(self):
        with tempfile.TemporaryDirectory() as d:
            st = State(Path(d) / "s.json")
            rows = evaluate(sample(), ME, TODAY)
            new, rem = plan(rows, ME, st, TODAY)
            self.assertTrue(new and not rem)
            self.assertFalse(any(v.level == "제외" for _, v in new))
            st.save(TODAY)
            # 다음날: 새 공고 없음, 접수 D-1·D-0 리마인더
            st2 = State(Path(d) / "s.json")
            tomorrow = date(2026, 10, 14)
            new2, rem2 = plan(evaluate(sample(), ME, tomorrow), ME, st2, tomorrow)
            self.assertEqual(new2, [])
            heads = {n.title[:6]: h for n, _, h in rem2}
            self.assertTrue(any("오늘 접수 시작" in h for h in heads.values()))
            # 같은 리마인더는 두 번 안 보낸다
            _, rem3 = plan(evaluate(sample(), ME, tomorrow), ME, st2, tomorrow)
            self.assertEqual(rem3, [])

    def test_embed_shape(self):
        n = sample()[-2]
        e = discord.embed(n, judge(n, ME, TODAY))
        self.assertLessEqual(len(e["title"]), 256)
        json.dumps(e)


if __name__ == "__main__":
    unittest.main()


class AccountTest(unittest.TestCase):
    def test_labels_without_filter(self):
        rows = evaluate(sample(), ME, TODAY)          # 기본: 빼지 않고 표시만
        self.assertEqual(by_title(rows, "든든전세").account, "불필요")
        self.assertEqual(by_title(rows, "청계 예시 무순위").account, "불필요")
        apt = by_title(rows, "서울 민영")
        self.assertEqual((apt.level, apt.account), ("확인", "사용"))
        n = next(n for n, _ in rows if "서울 민영" in n.title)
        self.assertIn("당첨되면 통장 효력 소멸", discord.embed(n, apt)["description"])

    def test_modes(self):
        n = lh.to_notice({"PAN_ID": "9", "PAN_NM": "서울 ○○ 행복주택 입주자모집", "CNP_CD_NM": "서울특별시",
                          "AIS_TP_CD_NM": "행복주택", "CLSG_DT": "2026.10.20"})
        self.assertEqual(judge(n, ME, TODAY).account, "가입만")
        self.assertEqual(judge(n, {**ME, "account_mode": "불필요만"}, TODAY).level, "제외")
        self.assertEqual(judge(n, {**ME, "account_mode": "가입만까지"}, TODAY).level, "추천")
        apt = by_title(evaluate(sample(), {**ME, "account_mode": "가입만까지"}, TODAY), "서울 민영")
        self.assertEqual(apt.level, "제외")
