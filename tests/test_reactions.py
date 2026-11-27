"""Discord 완료 처리의 메시지 연결, 사용자 확인, 상태 병합 검증."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import requests

from cheong import discord
from cheong.eligibility import Verdict
from cheong.main import plan
from cheong.models import Notice
from cheong.state import State
from cheong.sync import union

TODAY = date(2026, 11, 27)
WEBHOOK = "https://discord.test/api/webhooks/123/token"
CFG = {"webhook": WEBHOOK, "bot_token": "TEST_BOT_TOKEN", "user_id": "456"}


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    return result


class DiscordCompletionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.state = State(self.path)
        close = TODAY + timedelta(days=1)
        self.a = Notice("LH", "1", "A", end=close)
        self.b = Notice("LH", "2", "B", end=close)
        verdict = Verdict("추천", "임대")
        self.rows = [(self.a, verdict), (self.b, verdict)]
        self.cards = [(n.key, discord.embed(n, v, TODAY)) for n, v in self.rows]

    def test_checked_notice_stays_suppressed_after_reload(self):
        for notice, _ in self.rows:
            self.state.mark_seen(notice.key, TODAY)
        messages = [response({"channel_id": "12", "id": mid}) for mid in ("100", "200")]
        with patch("cheong.discord.requests.post", side_effect=messages) as post, \
                patch("cheong.discord.time.sleep"):
            discord.send_notices(CFG, self.state, "새 공고 2건", self.cards)
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["params"], {"wait": "true"})
            self.assertEqual(len(call.kwargs["json"]["embeds"]), 1)
            self.assertIn("✅", call.kwargs["json"]["content"])
        self.state.save(TODAY)

        state = State(self.path)
        reactions = [response([{"id": "456"}]), response([{"id": "789"}])]
        with patch("cheong.discord.requests.get", side_effect=reactions) as get:
            self.assertEqual(discord.sync_completions(state, CFG["bot_token"], CFG["user_id"],
                                                     {self.a.key, self.b.key}), 1)
        for call, mid in zip(get.call_args_list, ("100", "200")):
            self.assertEqual(call.args[0], f"https://discord.com/api/v10/channels/12/messages/{mid}"
                                           "/reactions/%E2%9C%85")
            self.assertEqual(call.kwargs["headers"], {"Authorization": "Bot TEST_BOT_TOKEN"})
        state.save(TODAY)

        state = State(self.path)
        self.assertEqual(state.done, {self.a.key})
        self.assertEqual(set(state.tracked_messages), {"200"})
        self.assertNotIn(CFG["bot_token"], self.path.read_text())
        self.assertNotIn(CFG["user_id"], self.path.read_text())
        new, reminders = plan(self.rows, {}, state, TODAY + timedelta(days=1))
        self.assertEqual(new, [])
        self.assertEqual([n.key for n, _, _ in reminders], [self.b.key])

    def test_dry_run_and_one_message_per_notice_without_bot(self):
        with patch("cheong.discord.requests.post", return_value=response(None, 204)) as post, \
                patch("cheong.discord.time.sleep"), patch("builtins.print"):
            discord.send_notices(CFG, self.state, "새 공고 2건", self.cards, dry_run=True)
            post.assert_not_called()
            self.assertEqual(self.state.tracked_messages, {})
            discord.send_notices({"webhook": WEBHOOK}, self.state, "새 공고 2건", self.cards)
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            self.assertNotIn("params", call.kwargs)
            self.assertEqual(len(call.kwargs["json"]["embeds"]), 1)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["content"], "새 공고 2건")
        self.assertNotIn("content", post.call_args_list[1].kwargs["json"])
        self.assertEqual(self.state.tracked_messages, {})

    def test_deleted_message_does_not_block_other_reactions(self):
        self.state.track_message(self.a.key, "12", "100")
        self.state.track_message(self.b.key, "12", "200")
        reactions = [response(None, 404), response([{"id": "456"}])]
        with patch("cheong.discord.requests.get", side_effect=reactions):
            self.assertEqual(discord.sync_completions(self.state, CFG["bot_token"], CFG["user_id"],
                                                     {self.a.key, self.b.key}), 1)
        self.assertEqual(self.state.done, {self.b.key})

    def test_mac_can_record_message_for_actions_without_bot_token(self):
        cfg = {"webhook": WEBHOOK, "discord_track_reactions": True}
        with patch("cheong.discord.requests.post", return_value=response({"channel_id": "1", "id": "2"})), \
                patch("cheong.discord.time.sleep"):
            discord.send_notices(cfg, self.state, "LH", self.cards[:1])
        self.assertEqual(self.state.tracked_messages, {"2": {"key": self.a.key, "channel_id": "1"}})

    def test_unreadable_channel_does_not_block_other_channels(self):
        self.state.track_message(self.a.key, "12", "100")
        self.state.track_message(self.a.key, "12", "110")
        self.state.track_message(self.b.key, "34", "200")
        reactions = [response(None, 403), response([{"id": "456"}])]
        with patch("cheong.discord.requests.get", side_effect=reactions) as get:
            self.assertEqual(discord.sync_completions(self.state, CFG["bot_token"], CFG["user_id"],
                                                     {self.a.key, self.b.key}), 1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.state.done, {self.b.key})

    def test_merge_drops_tracking_for_notice_completed_by_other_runner(self):
        a = {"done": [self.a.key], "seen": {self.a.key: TODAY.isoformat()}}
        b = {"seen": {self.a.key: TODAY.isoformat(), self.b.key: TODAY.isoformat()},
             "tracked_messages": {"100": {"key": self.a.key, "channel_id": "12"},
                                  "200": {"key": self.b.key, "channel_id": "12"}}}
        merged = union(a, b)
        self.assertEqual(merged, union(b, a))
        self.assertEqual(merged["done"], [self.a.key])
        self.assertEqual(merged["tracked_messages"], {"200": b["tracked_messages"]["200"]})
