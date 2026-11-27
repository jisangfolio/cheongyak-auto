"""디스코드 웹훅 알림.

서버 설정 → 연동 → 웹후크 → 새 웹후크 → URL 복사 → DISCORD_WEBHOOK_URL 에 넣는다.
한 메시지에 임베드 최대 10개, 429(속도 제한)면 retry_after 만큼 기다렸다 다시 보낸다.
"""
import time
from urllib.parse import quote

import requests

from .util import safe_http_error, today_kst

COLORS = {"추천": 0x2ECC71, "확인": 0xF1C40F, "리마인더": 0xE67E22, "info": 0x5865F2}
EMOJI = {"청약홈": "🏢", "LH": "🏠", "SH": "🏙️", "청년안심": "🧑‍💼"}


def _date_label(day, today):
    year = f"{day.year}년 " if day.year != today.year else ""
    return f"{year}{day.month}월 {day.day}일({'월화수목금토일'[day.weekday()]})"


def _schedule(n, today, reminder):
    if n.source == "사회주택" and n.status == "공실 있음":
        return ["**공실 표시 · 운영사에 문의**"]
    begin = _date_label(n.begin, today) if n.begin else None
    end = _date_label(n.end, today) if n.end else None
    if n.end == today:
        lines = [f"**오늘 마감 · {end}**"]
        if n.begin != today:
            lines.append(f"접수 시작 {begin}" if begin else "접수 시작일 확인 필요")
        return lines
    if n.begin and n.begin >= today and reminder != "end":
        days = (n.begin - today).days
        start = f"{begin} 접수 시작 · D-{days}" if days else f"오늘 접수 시작 · {begin}"
        return [f"**{start}**", f"마감 {end}" if end else "마감일 확인 필요"]
    if n.end:
        days = (n.end - today).days
        if days < 0:
            return [f"**접수 마감 · {end}**"]
        status = "접수 중 · " if n.begin and n.begin <= today else ""
        return [f"**{status}마감 {end} · D-{days}**",
                f"접수 시작 {begin}" if begin else "접수 시작일 확인 필요"]
    if begin:
        return ["**마감일 확인 필요**", f"접수 시작 {begin}"]
    return ["**접수 일정 확인 필요**"]


def embed(n, v, today=None, *, reminder=None):
    from .eligibility import ACCOUNT_LABEL
    today = today or today_kst()
    lines = _schedule(n, today, reminder)
    lines.append(f"💳 청약통장: **{ACCOUNT_LABEL.get(v.account, v.account)}**")
    lines += [f"{'✅' if v.level == '추천' else '🟡'} " + " · ".join(v.reasons)] if v.reasons else []
    lines += [f"💡 {t}" for t in v.tips]
    fields = [
        {"name": "유형", "value": (n.category or v.kind)[:100], "inline": True},
        {"name": "지역", "value": n.region or "-", "inline": True},
    ]
    if n.announce:
        fields.append({"name": "발표", "value": _date_label(n.announce, today), "inline": True})
    if n.households:
        fields.append({"name": "표시된 공실" if n.source == "사회주택" else "세대수",
                       "value": str(n.households), "inline": True})
    if n.address:
        fields.append({"name": "주소", "value": n.address[:200], "inline": False})
    e = {
        "title": f"{EMOJI.get(n.source, '📌')} [{n.source}] {n.title}"[:256],
        "description": "\n".join(lines)[:1500],
        "color": COLORS["리마인더"] if reminder else COLORS.get(v.level, COLORS["info"]),
        "fields": fields,
        "footer": {"text": f"판정: {v.level} · {v.kind} · 통장 {v.account}"},
    }
    if n.url.startswith("http"):
        e["url"] = n.url
    return e


def _request(method, url, *, accept_status=(), **kwargs):
    for _ in range(3):
        try:
            r = method(url, timeout=15, **kwargs)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)))
                continue
            if r.status_code not in accept_status:
                r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            raise safe_http_error(e, url) from None
    # 429가 계속되면 전송에 성공한 것이 아니다. 상태 저장 전에 실패시킨다.
    raise safe_http_error(requests.exceptions.HTTPError(response=r), url) from None


def _embed_chunks(embeds):
    chunk, total = [], 0
    for embed in embeds:
        text = [embed.get("title", ""), embed.get("description", ""),
                embed.get("footer", {}).get("text", ""), embed.get("author", {}).get("name", "")]
        for field in embed.get("fields", []):
            text.extend((field["name"], field["value"]))
        length = sum(len(value) for value in text)
        if chunk and (len(chunk) == 10 or total + length > 6000):
            yield chunk
            chunk, total = [], 0
        chunk.append(embed)
        total += length
    yield chunk


def send(webhook, content=None, embeds=None, dry_run=False, *, wait=False):
    sent = []
    for i, chunk in enumerate(_embed_chunks(embeds or [])):
        payload = {"username": "청약 알리미", "embeds": chunk}
        if content and i == 0:
            payload["content"] = content[:2000]
        if dry_run or not webhook:
            print(f"[discord:dry] {payload.get('content', '')}")
            for e in chunk:
                print(f"   - {e['title']}  | {e['footer']['text']}")
                first_line = e.get("description", "").partition("\n")[0]
                if first_line:
                    print(f"     {first_line}")
            continue
        options = {"params": {"wait": "true"}} if wait else {}
        r = _request(requests.post, webhook, json=payload, **options)
        if wait:
            try:
                message = r.json()
                sent.append((message["channel_id"], message["id"]))
            except (ValueError, KeyError, TypeError):
                # 전송에 성공한 공고를 응답 형식 때문에 중복 발송하지 않는다.
                print("[discord] 응답에 메시지 ID가 없어 완료 반응을 추적할 수 없습니다.")
        time.sleep(0.5)
    if wait:
        return sent


def send_notices(cfg, state, content, notices, dry_run=False, *, confirm=False):
    """공고마다 메시지를 하나씩 보내고, 완료 기능을 쓰면 메시지 ID를 저장한다."""
    webhook = cfg["webhook"]
    tracking = bool(webhook and (cfg.get("discord_track_reactions")
                                or (cfg.get("bot_token") and cfg.get("user_id"))))
    hint = "확인한 공고는 이 메시지에 ✅ 반응을 남기면 다음 알림부터 제외됩니다."
    delivered = []
    for i, (key, card) in enumerate(notices):
        heading = "\n".join(filter(None, (content if i == 0 else None, hint if tracking else None)))
        receipts = send(webhook, heading, [card], dry_run, wait=confirm or tracking) or []
        if tracking:
            for channel_id, message_id in receipts:
                state.track_message(key, channel_id, message_id)
        delivered.extend(receipts)
    return delivered


def _reacted_by_user(url, bot_token, user_id):
    params = {"limit": 100}
    while True:
        r = _request(requests.get, url, accept_status=(403, 404),
                     headers={"Authorization": f"Bot {bot_token}"}, params=params)
        if r.status_code == 403:
            return None
        if r.status_code == 404:  # 메시지가 삭제된 경우
            return False
        users = r.json()
        if any(user["id"] == user_id and not user.get("bot") for user in users):
            return True
        if len(users) < params["limit"]:
            return False
        params = {**params, "after": users[-1]["id"]}


def sync_completions(state, bot_token, user_id, notice_keys):
    """현재 진행 중인 공고에서 지정 계정의 ✅를 찾아 완료 상태를 저장한다."""
    emoji = quote("✅", safe="")
    completed = 0
    checked = 0
    blocked_channels = set()
    for message_id, info in state.tracked_messages.items():
        key = info["key"]
        channel_id = info["channel_id"]
        if key not in notice_keys or state.is_done(key) or channel_id in blocked_channels:
            continue
        url = (f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
               f"/reactions/{emoji}")
        try:
            reacted = _reacted_by_user(url, bot_token, user_id)
        except (ValueError, KeyError, TypeError):
            print("[discord] 완료 반응 응답 형식을 확인해 주세요.")
            break
        except requests.exceptions.RequestException as e:
            print(f"[discord] 완료 반응 확인 실패: {e}")
            break
        if reacted is None:
            print(f"[discord] 완료 반응을 읽을 채널 권한을 확인해 주세요 ({channel_id}).")
            blocked_channels.add(channel_id)
        else:
            checked += 1
            if reacted:
                state.mark_done(key)
                completed += 1
    if checked:
        print(f"[discord] 완료 반응 확인 {checked}개 메시지")
    if completed:
        print(f"[discord] 완료 처리 {completed}건")
    return completed
