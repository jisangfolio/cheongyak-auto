from datetime import date
from unittest import TestCase

from cheong.sources.youth import apply_period, from_json


class YouthScheduleTest(TestCase):
    def test_single_date_and_two_times_are_same_day(self):
        content = ("<p>■모집공고 : ‘26. 11. 26. (목)</p>"
                   "<p><span><b>■청약신청 : ‘26. 11. 30. (월) 09:00 ~ 17:00</b></span></p>"
                   "<p>■서류심사 대상자 발표 : ‘26. 12. 01. (화) 16:00</p>")
        self.assertEqual(apply_period(content), (date(2026, 11, 30), date(2026, 11, 30)))

    def test_inline_spans_keep_full_qualifying_period(self):
        content = ("<p><b><span>■청약신청 : ‘26. 11. 30. (월) ~</span>"
                   "<span> 12. 02. (수) 00:00 ~ 23:00</span></b></p>")
        self.assertEqual(apply_period(content), (date(2026, 11, 30), date(2026, 12, 2)))

    def test_explicit_period_takes_precedence_over_summary_date(self):
        row = {"boardId": 6887, "optn4": "2026-12-01",
               "content": "<p>■청약신청 : ‘26. 11. 30. (월) 00:00 ~ 12. 01. (화) 23:00</p>"}
        notice = from_json(row)
        self.assertEqual((notice.begin, notice.end), (date(2026, 11, 30), date(2026, 12, 1)))

    def test_open_ended_period_does_not_take_following_section_date(self):
        content = ("<p>■청약신청 : ‘26. 11. 30. (월) 09:00 ~ 소진 시</p>"
                   "<p>■서류심사 대상자 발표 : ‘26. 12. 01. (화) 16:00</p>")
        self.assertEqual(apply_period(content, date(2026, 11, 30)), (date(2026, 11, 30), None))
