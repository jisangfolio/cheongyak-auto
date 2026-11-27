from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

from cheong.eligibility import judge, kind_of
from cheong.models import Notice
from cheong.profile import DEFAULT
from cheong.sources import applyhome


TODAY = date(2026, 11, 27)
PROFILE = {**DEFAULT, "birth": "2000-06-01"}


class AudienceCoverageTest(TestCase):
    def test_social_housing_is_ignored_across_feeds(self):
        for notice in (
            Notice("사회주택", "1", "홍시주택"),
            Notice("SH", "2", "[토지임대부 사회주택] 옥류서원 입주자 모집"),
            Notice("SH", "3", "예비입주자 모집", category="사회적주택"),
        ):
            self.assertEqual(judge(notice, PROFILE, TODAY).level, "무시")

    def test_eligible_audience_is_kept_when_another_audience_does_not_match(self):
        titles = (
            "2026년 마포구 신혼부부,청년(수요자맞춤형)주택 잔여세대 입주자 모집 공고",
            "청년·고령자 행복주택 입주자 모집 공고",
        )
        for uid, title in enumerate(titles):
            with self.subTest(title=title):
                n = Notice("SH", str(uid), title, region="서울")
                self.assertEqual(judge(n, PROFILE, TODAY).level, "확인")

    def test_named_single_audiences_are_still_excluded_if_ineligible(self):
        titles = (
            "신혼·신생아 매입임대주택 입주자 모집공고",
            "강동구 청년창업가,예술인주택 잔여세대 모집 공고",
        )
        for uid, title in enumerate(titles):
            with self.subTest(title=title):
                n = Notice("SH", str(uid), title, region="서울")
                self.assertEqual(judge(n, PROFILE, TODAY).level, "제외")

    def test_sh_own_board_sale_uses_public_sale_profile_preference(self):
        n = Notice("SH", "1", "입주자 모집 공고", category="주택분양",
                   region="서울", extra={"board": "i-sh"})
        p = {**PROFILE, "want": {**PROFILE["want"], "공공분양": False}}
        v = judge(n, p, TODAY)
        self.assertEqual((v.kind, v.level), ("공공분양", "제외"))


class ApplyhomeCoverageTest(TestCase):
    def test_combined_endpoint_uses_actual_listing_type_for_profile_filter(self):
        cases = (
            ("0201", "도시형생활주택", "오피스텔", "제외"),
            ("0202", "오피스텔", "오피스텔", "제외"),
            ("0203", "민간임대", "민간임대", "확인"),
            ("", "민간임대", "민간임대", "확인"),
        )
        for code, category, kind, level in cases:
            with self.subTest(code=code, category=category):
                n = applyhome.to_notice({"HOUSE_NM": "예시주택", "PBLANC_NO": "2026000101",
                                         "SEARCH_HOUSE_SECD": code, "HOUSE_DTL_SECD_NM": category},
                                        applyhome.KINDS["urbty"][1])
                v = judge(n, PROFILE, TODAY)
                self.assertEqual((v.kind, v.level), (kind, level))

    def test_optional_supply_uses_its_own_endpoint_and_dates(self):
        item = {"HOUSE_NM": "예시 아파트", "PBLANC_NO": "2026000101",
                "HOUSE_SECD_NM": "임의공급", "SUBSCRPT_RCEPT_BGNDE": "20261127",
                "SUBSCRPT_RCEPT_ENDDE": "20261127", "PBLANC_URL": "https://www.applyhome.co.kr/x"}
        response = Mock()
        response.json.return_value = {"data": [item], "totalCount": 716, "matchCount": 1}
        cfg = {"keys": {"applyhome": "example"}, "sources": {"applyhome": {"kinds": ["opt"]}}}
        with patch("cheong.sources.applyhome.get", return_value=response) as get:
            notice, = applyhome.fetch(cfg, TODAY)
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].endswith("/getOPTLttotPblancDetail"))
        self.assertEqual((notice.begin, notice.end, kind_of(notice)), (TODAY, TODAY, "민영분양"))
        self.assertEqual(judge(notice, PROFILE, TODAY).account, "불필요")

    def test_late_page_failure_keeps_rows_from_successful_page(self):
        response = Mock()
        response.json.return_value = {"data": [{"PBLANC_NO": "2026000101"}], "matchCount": 2}
        with patch("cheong.sources.applyhome.get", side_effect=[response, RuntimeError("timeout")]) as get:
            items = applyhome._fetch_kind("example", "example", TODAY, per_page=1)
        self.assertEqual(items, [{"PBLANC_NO": "2026000101"}])
        self.assertEqual(get.call_count, 2)
