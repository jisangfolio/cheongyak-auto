"""공고 × 내 프로필 → 추천 / 확인 / 제외.

원칙: 공고 목록에는 제목·유형 정도만 있어서 세부 소득·자산 기준은 알 수 없다.
그래서 '구조적으로 확실히 안 되는 것'만 제외하고, 애매하면 '확인'으로 살린다.
(잘못 걸러서 놓치는 손해 > 알림 하나 더 받는 손해)
"""
import re
from dataclasses import dataclass, field

from .models import Notice
from .profile import age as calc_age

LEVELS = {"추천": 2, "확인": 1, "제외": 0, "무시": -1}

# 모집이 아닌 후속 안내(결과·서류·계약)는 알림 대상이 아니다
NOISE = re.compile(r"당첨자|서류심사|서류제출|계약\s*(체결|안내|일정)|결과\s*(발표|안내|공고)|순번|합격자|명단|동호수|정산")
RECRUIT = re.compile(r"모집|청약\s*접수|접수\s*안내|입주자\s*선정|공급")


@dataclass
class Verdict:
    level: str
    kind: str                       # 임대 / 공공분양 / 민영분양 / 오피스텔 / 민간임대
    reasons: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    account: str = "확인"            # 청약통장: 불필요 / 가입만 / 사용 / 확인

    @property
    def score(self):
        return LEVELS[self.level]


def _has(t, *words):
    return any(w in t for w in words)


def kind_of(n: Notice) -> str:
    t = n.text
    if n.source == "청약홈":
        if _has(t, "오피스텔", "도시형"):
            return "오피스텔"
        if _has(t, "민간임대"):
            return "민간임대"
        if _has(t, "국민", "공공", "신혼희망", "뉴:홈", "뉴홈"):
            return "공공분양"
        return "민영분양"
    if n.source == "SH" and n.extra.get("board") == "publicSale":
        return "공공분양"
    if n.source == "LH" and _has(t, "분양") and not _has(t, "임대"):
        return "공공분양"
    return "임대"


# 청약통장: 지원할 때 통장이 쓰이는가 (일반 규정 기준 — 공고마다 예외 가능)
#   불필요 : 통장 없이 지원
#   가입만 : 가입 사실만 확인, 당첨돼도 통장 유지 (임대)
#   사용   : 당첨되면 통장 효력 소멸 (분양·분양전환 임대)
#   확인   : 분류 불가 → 공고문 확인
ACCOUNT_FREE = ("매입임대", "전세임대", "든든전세", "청년안심", "역세권", "민간임대", "오피스텔",
                "도시형", "무순위", "잔여", "임의공급", "희망하우징", "기숙사", "영구임대",
                "사회주택", "수요자맞춤형")
ACCOUNT_USE = ("신혼희망타운", "공공분양", "뉴홈", "뉴:홈", "분양전환", "10년 공공임대", "5년 공공임대")
ACCOUNT_KEEP = ("행복주택", "국민임대", "국민공공임대")
ACCOUNT_LABEL = {
    "불필요": "🟢 필요 없음",
    "가입만": "🔵 가입만 필요 — 당첨돼도 통장 유지",
    "사용": "🔴 사용 — 당첨되면 통장 효력 소멸",
    "확인": "⚪ 공고문에서 확인",
}
# account_mode: 어떤 공고를 아예 빼는지 (기본은 빼지 않고 표시만)
ACCOUNT_MODES = {"불필요만": ("사용", "가입만"), "가입만까지": ("사용",), "상관없음": ()}


def account_need(n: Notice, kind: str) -> str:
    t = n.text
    if _has(t, *ACCOUNT_FREE) or kind in ("오피스텔", "민간임대"):
        return "불필요"
    if _has(t, *ACCOUNT_USE) or kind in ("공공분양", "민영분양"):
        return "사용"
    if _has(t, *ACCOUNT_KEEP):
        return "가입만"
    return "확인"


def judge(n: Notice, p: dict, today) -> Verdict:
    t = n.text
    kind = kind_of(n)
    a = calc_age(p, today)
    marital = p.get("marital", "미혼")
    single = marital == "미혼"
    newly = marital in ("예비신혼", "신혼") or p.get("newborn") or p.get("single_parent")
    v = Verdict("확인", kind)

    def out(reason):
        v.level, v.reasons = "제외", [reason]
        return v

    # 0) 후속 안내는 무시
    if NOISE.search(n.title) and not RECRUIT.search(n.title.split("결과")[-1]):
        v.level, v.reasons = "무시", ["모집이 아닌 후속 안내"]
        return v

    # 1) 지역·관심 유형
    regions = p.get("regions") or []
    if regions and n.region and n.region not in regions:
        return out(f"관심 지역 아님({n.region})")
    if not (p.get("want") or {}).get(kind, True):
        return out(f"관심 유형 아님({kind})")

    # 1-1) 청약통장
    v.account = account_need(n, kind)
    blocked = ACCOUNT_MODES.get(p.get("account_mode", "상관없음"), ())
    if v.account in blocked:
        return out("청약통장을 쓰는 공고" if v.account == "사용" else "청약통장 가입이 필요한 공고")

    # 2) 무주택
    if not p.get("homeless", True) and kind not in ("오피스텔", "민간임대"):
        return out("유주택자는 대부분 지원 불가")

    # 3) 대상 계층이 정해진 공고
    if _has(t, "신혼", "신생아", "미리내집", "예비신혼"):
        if not newly:
            return out("신혼·신생아·예비신혼·한부모 대상")
        v.level = "추천"
        v.reasons.append("신혼·신생아 대상에 해당")
    if _has(t, "고령자", "어르신", "은빛", "노인", "실버"):
        if a is None or a < 65:
            return out("만 65세 이상 고령자 대상")
    if _has(t, "장애인") and not p.get("disabled"):
        return out("장애인 대상")
    if _has(t, "영구임대", "수급자", "주거취약", "쪽방", "비주택") and not p.get("low_income"):
        return out("수급자·저소득 취약계층 대상")
    if _has(t, "예술인", "창업가") and not p.get("artist_or_startup"):
        return out("예술인·청년창업가 대상")
    if _has(t, "다자녀", "다둥이") and int(p.get("children") or 0) < 2:
        return out("다자녀 대상")
    if _has(t, "대학생", "희망하우징", "공공기숙사") and not _has(t, "청년") and not p.get("student"):
        return out("대학생 대상")

    youth_ok = a is not None and 19 <= a <= 39
    if _has(t, "청년"):
        if a is not None and not youth_ok:
            return out("만 19~39세 청년 대상")
        v.level = "추천"
        v.reasons.append("청년 대상" + (f"(만 {a}세)" if a is not None else ""))

    # 4) 유형별 판단
    if kind == "임대":
        if _has(t, "든든전세"):
            v.level = "추천"
            v.reasons.append("든든전세: 무주택이면 소득·자산 무관")
        elif _has(t, "행복주택"):
            if youth_ok and single:
                v.level = "추천"
                v.reasons.append("행복주택 청년 계층 지원 가능")
            v.tips.append("청년 계층은 소득·자산 기준 있음 — 공고문 확인")
        elif _has(t, "장기전세"):
            v.reasons.append("장기전세: 무주택 세대 + 소득·자산 기준")
            if not p.get("household_homeless", True):
                v.tips.append("세대원 중 주택 소유자가 있으면 불가")
        elif _has(t, "국민임대", "국민공공임대", "통합공공임대"):
            v.reasons.append("소득 기준(국민임대는 도시근로자 70% 안팎) 확인 필요")
        elif _has(t, "재개발임대"):
            v.reasons.append("재개발임대: 철거세입자 우선, 일반은 저소득 위주")
        elif _has(t, "매입임대", "전세임대") and not v.reasons:
            v.reasons.append("일반 매입·전세임대는 수급자·저소득 우선 — 순위 확인")
        elif n.source == "청년안심":
            v.level = "추천"
        if not v.reasons:
            v.reasons.append("임대 공고 — 자격 요건 공고문 확인")
    elif kind == "공공분양":
        if youth_ok and single and not p.get("ever_owned"):
            v.level = "추천"
            v.reasons.append("청년 특별공급 대상 구조(만19~39·미혼·무주택)")
        elif not p.get("ever_owned"):
            v.reasons.append("생애최초·일반공급 가능성")
        if int(p.get("account_years") or 0) < 2:
            v.tips.append("수도권 공공분양 1순위는 통장 2년·24회 이상 필요(특공은 6개월)")
        if p.get("household") != "단독세대주" and not p.get("household_homeless", True):
            v.tips.append("세대원 중 유주택자가 있으면 일반공급 불리 → 세대분리 검토")
    elif kind == "민영분양":
        if _has(t, "무순위", "잔여"):
            v.reasons.append("무순위: 무주택 + 해당 지역 거주 요건 확인")
        else:
            v.reasons.append("민영 APT: 추첨제 물량 위주로 노려볼 만함")
        if a is not None and a < 30 and single:
            v.tips.append("만 30세 전 미혼은 무주택 가점 0점 → 가점제보다 추첨제")
        if not p.get("household_homeless", True):
            v.tips.append("세대원 유주택이면 1순위 제한될 수 있음")
    elif kind in ("오피스텔", "민간임대"):
        v.reasons.append(f"{kind}: 청약통장·무주택 요건이 느슨함")

    return v
