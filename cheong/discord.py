"""디스코드 웹훅 알림.

서버 설정 → 연동 → 웹후크 → 새 웹후크 → URL 복사 → DISCORD_WEBHOOK_URL 에 넣는다.
한 메시지에 임베드 최대 10개, 429(속도 제한)면 retry_after 만큼 기다렸다 다시 보낸다.
"""
import time

import requests

COLORS = {"추천": 0x2ECC71, "확인": 0xF1C40F, "리마인더": 0xE67E22, "info": 0x5865F2}
EMOJI = {"청약홈": "🏢", "LH": "🏠", "SH": "🏙️", "청년안심": "🧑‍💼"}


def _d(x):
    return x.strftime("%m/%d") if x else "?"


def _period(n):
    if n.begin and n.end:
        return f"{_d(n.begin)} ~ {_d(n.end)}"
    if n.begin:
        return f"{_d(n.begin)} 시작"
    if n.end:
        return f"~ {_d(n.end)} 마감"
    return "공고문 확인"


def embed(n, v, headline=None, today=None):
    from .eligibility import ACCOUNT_LABEL
    lines = []
    if headline:
        lines.append(f"**{headline}**")
    lines.append(f"💳 청약통장: **{ACCOUNT_LABEL.get(v.account, v.account)}**")
    lines += [f"{'✅' if v.level == '추천' else '🟡'} " + " · ".join(v.reasons)] if v.reasons else []
    lines += [f"💡 {t}" for t in v.tips]
    fields = [
        {"name": "유형", "value": (n.category or v.kind)[:100], "inline": True},
        {"name": "지역", "value": n.region or "-", "inline": True},
        {"name": "접수", "value": _period(n), "inline": True},
    ]
    if n.announce:
        fields.append({"name": "발표", "value": n.announce.strftime("%Y-%m-%d"), "inline": True})
    if n.households:
        fields.append({"name": "세대수", "value": str(n.households), "inline": True})
    if n.address:
        fields.append({"name": "주소", "value": n.address[:200], "inline": False})
    e = {
        "title": f"{EMOJI.get(n.source, '📌')} [{n.source}] {n.title}"[:256],
        "description": "\n".join(lines)[:1500],
        "color": COLORS["리마인더"] if headline else COLORS.get(v.level, COLORS["info"]),
        "fields": fields,
        "footer": {"text": f"판정: {v.level} · {v.kind} · 통장 {v.account}"},
    }
    if n.url.startswith("http"):
        e["url"] = n.url
    return e


def send(webhook, content=None, embeds=None, dry_run=False):
    embeds = embeds or []
    chunks = [embeds[i:i + 10] for i in range(0, len(embeds), 10)] or [[]]
    for i, chunk in enumerate(chunks):
        payload = {"username": "청약 알리미", "embeds": chunk}
        if content and i == 0:
            payload["content"] = content[:2000]
        if dry_run or not webhook:
            print(f"[discord:dry] {payload.get('content', '')}")
            for e in chunk:
                print(f"   - {e['title']}  | {e['footer']['text']}")
            continue
        for _ in range(3):
            r = requests.post(webhook, json=payload, timeout=15)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)))
                continue
            r.raise_for_status()
            break
        time.sleep(0.5)
