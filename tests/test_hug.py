import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from cheong.sources import hug


def _page(rows):
    return f"""<table class="mb d_list">
      <caption>입주자 모집 예정 주택 목록</caption>
      <thead><tr><th>번호</th><th>공고일자</th><th>청약 접수기간</th><th>시도</th><th>주소</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _row(region, posted="2026.09.30.", period="2026.09.30. 10:00 ~ 2026.10.12. 17:00"):
    return f"<tr><td>12</td><td>{posted}</td><td>{period}</td><td>{region}</td><td>공개 주소</td></tr>"


class HugSourceTest(unittest.TestCase):
    def test_seoul_round_is_reported_once_for_multiple_units(self):
        body = _page(_row("서울특별시") + _row("서울특별시") + _row("경기도", "2026.10.02."))
        with patch("cheong.sources.hug.get", return_value=SimpleNamespace(content=body.encode("cp949"))) as get:
            notices = hug.fetch({}, date(2026, 10, 1))

        self.assertEqual(get.call_args.args[1]["CMB_SIDO"], "01")
        self.assertEqual(len(notices), 1)
        notice = notices[0]
        self.assertEqual((notice.key, notice.region, notice.category), ("HUG:2026-09-30", "서울", "든든전세주택"))
        self.assertEqual((notice.begin, notice.end), (date(2026, 9, 30), date(2026, 10, 12)))
        self.assertIn("CMB_SIDO=01", notice.url)

    def test_empty_round_is_valid_but_missing_table_is_an_error(self):
        empty = _page('<tr><td colspan="5">등록된 게시물이 없습니다.</td></tr>')
        self.assertEqual(hug.parse_list(empty), [])
        with self.assertRaisesRegex(ValueError, "모집 표"):
            hug.parse_list("<html>서비스 점검 중</html>")

    def test_broken_reception_period_surfaces_parsing_error(self):
        with self.assertRaisesRegex(ValueError, "모집 일정"):
            hug.parse_list(_page(_row("서울특별시", period="9월~10월")))
