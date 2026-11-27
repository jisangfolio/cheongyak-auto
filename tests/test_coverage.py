import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cheong import discord, main
from cheong.eligibility import Verdict
from cheong.models import Notice
from cheong.sources import lh, sh
from cheong.state import State


class CoverageTest(unittest.TestCase):
    def test_sh_detail_requires_matching_title_and_application_dates(self):
        html = """
          <div class="board-detail">
            <table><tr><td class="tlt">서울 장기안심주택 입주자 모집</td></tr>
            <tr><td>
              <p>■ <span>인터넷 청약접수</span><span>: 2026.12.14.(</span> 월 ) 10 시 ~ 2026.12.16.( 수 ) 17 시</p>
              <p>■ 서류접수기간: 2026.12.20. ~ 2026.12.24.</p>
            </td></tr></table>
          </div>
        """
        notice = Notice("SH", "1", "서울 장기안심주택 입주자 모집")
        self.assertEqual(sh.parse_reception(html, notice), (date(2026, 12, 14), date(2026, 12, 16)))
        notice.title = "다른 공고"
        self.assertIsNone(sh.parse_reception(html, notice))

    def test_lh_seoul_keeps_official_notice_id_and_uses_correction(self):
        head = ("번호", "공고 세부유형명", "공고명", "지역", "공고게시일", "마감일", "상태", "링크")
        cells = "".join(f"<th>{name}</th>" for name in head)
        template = """
          <tr><td>1</td><td>{category}</td><td>{title}</td><td>서울특별시</td>
          <td>2026-11-24</td><td>2026-12-01</td><td>{status}</td>
          <td><a href="https://apply.lh.or.kr/example?panId={uid}">바로가기</a></td></tr>
        """
        revised = template.format(title="[정정공고] 행복주택 모집", status="공고중", uid="2", category="행복주택")
        original = template.format(title="행복주택 모집", status="정정공고중", uid="1", category="행복주택")
        sale = template.format(title="서울 분양주택 모집", status="공고중", uid="3", category="분양주택")

        def board(url, params, **kwargs):
            if url == lh.SEOUL_LIST:
                body, navigation = original + revised, ""
            elif url == lh.SEOUL_SALE_LISTS["05"]:
                self.assertEqual(params["aisTpCd"], "05")
                self.assertEqual(params["supplyType"], "publicSale")
                body = sale
                navigation = ('<a href="/site/main/lh/publicSale/05/list?cp=2">2</a>'
                              if params["cp"] == 1 else "")
                if params["cp"] == 1:
                    body = sale.replace("panId=3", "panId=4")
            else:
                self.assertEqual(params["aisTpCd"], "39")
                return SimpleNamespace(text="")
            return SimpleNamespace(text=(
                f'<div class="board-list"><table><thead><tr>{cells}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>{navigation}'
            ))

        with patch("cheong.sources.lh.get", side_effect=board) as get:
            notices = lh.fetch_seoul()
        self.assertEqual(get.call_count, 4)
        self.assertEqual([(n.key, n.end) for n in notices],
                         [(f"LH:{uid}", date(2026, 12, 1)) for uid in ("2", "4", "3")])

    def test_discord_chunks_include_embed_text_limit(self):
        large = [{"description": "가" * 1500, "title": str(i)} for i in range(8)]
        self.assertEqual([len(chunk) for chunk in discord._embed_chunks(large)], [3, 3, 2])
        self.assertEqual([len(chunk) for chunk in discord._embed_chunks([{}] * 11)], [10, 1])

    def test_replay_ignores_seen_but_keeps_completed_and_is_read_only_by_default(self):
        today = date(2026, 11, 27)
        a, b = Notice("SH", "1", "A", end=today), Notice("SH", "2", "B", end=today)
        cfg = {"webhook": "https://example.test", "sources": {"sh": {}, "hug": {"allow_empty": True}}}
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / "state.json")
            state.mark_seen(a.key, today)
            state.mark_done(b.key)
            with (
                patch("cheong.main.State", return_value=state),
                patch("cheong.main.load_config", return_value=cfg),
                patch("cheong.main.profile.load", return_value={}),
                patch("cheong.main.today_kst", return_value=today),
                patch("cheong.main.collect", return_value=([a, b], {"sh": 2, "hug": 0})) as collect,
                patch("cheong.main.judge", return_value=Verdict("추천", "임대")),
                patch("cheong.main._source_filter", return_value=(set(), set())),
                patch("cheong.main.discord.send_notices") as send,
            ):
                main.cmd_replay(SimpleNamespace(send=False))
                self.assertTrue(send.call_args.kwargs["dry_run"])
                self.assertEqual([key for key, _ in send.call_args.args[3]], [a.key])
                self.assertFalse(state.path.exists())
                send.reset_mock()
                collect.return_value = ([a], {"sh": 1, "lh": None})
                with self.assertRaises(SystemExit):
                    main.cmd_replay(SimpleNamespace(send=True))
                send.assert_not_called()
