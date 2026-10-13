"""처음 한 번 하는 설문 → profile.json.

  python -m cheong setup          # 대화형 설문
  python -m cheong setup --print  # 저장된 프로필을 GitHub Secret(PROFILE_JSON)용 한 줄로 출력

실행 시 프로필은 (1) 환경변수 PROFILE_JSON (2) profile.json 순서로 읽는다.
공개 저장소라면 profile.json 을 커밋하지 말고 Secret 으로만 넣는다(.gitignore 에 포함).
"""
import json
import os
from datetime import date
from pathlib import Path

from .util import parse_date, today_kst

PROFILE_FILE = Path(__file__).resolve().parent.parent / "profile.json"

DEFAULT = {
    "birth": "",                 # YYYY-MM-DD 또는 YYYY
    "marital": "미혼",           # 미혼 | 예비신혼 | 신혼(혼인 7년 이내) | 기혼(7년 초과)
    "children": 0,
    "newborn": False,            # 2세 미만 자녀(또는 임신 중)
    "single_parent": False,
    "homeless": True,            # 본인 무주택
    "ever_owned": False,         # 과거 주택 소유 이력
    "household": "단독세대주",    # 단독세대주 | 부모님세대원 | 기타
    "household_homeless": True,  # 세대원 전원 무주택인가
    "employed": True,
    "student": False,
    "monthly_income": None,      # 세전 월소득(만원)
    "assets": 0,                 # 총자산(만원)
    "car": 0,                    # 자동차가액(만원)
    "low_income": False,         # 기초수급·차상위
    "disabled": False,
    "artist_or_startup": False,
    "account_years": 0,          # 청약통장 가입 기간(년)
    "account_payments": 0,       # 납입 횟수
    "residence": "서울",          # 거주 시도
    "residence_since": "",       # 전입 YYYY-MM
    "regions": ["서울"],          # 알림 받을 시도
    "want": {"임대": True, "공공분양": True, "민영분양": True, "오피스텔": False, "민간임대": True},
    "account_mode": "상관없음",   # 상관없음(표시만) | 가입만까지 | 불필요만
    "min_level": "확인",          # 추천만 받으려면 "추천"
    "remind_days": 2,            # 접수 시작/마감 N일 전 리마인더
}


def load():
    raw = os.environ.get("PROFILE_JSON")
    if raw:
        data = json.loads(raw)
    elif PROFILE_FILE.exists():
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    else:
        raise SystemExit("프로필이 없습니다. 먼저 `python -m cheong setup` 으로 설문을 해 주세요.")
    prof = json.loads(json.dumps(DEFAULT))
    prof.update(data)
    prof["want"] = {**DEFAULT["want"], **(data.get("want") or {})}
    return prof


def age(prof, today=None):
    """만 나이. 출생연도만 있으면 그 해 생일이 지났다고 가정하지 않고 보수적으로 계산."""
    today = today or today_kst()
    b = str(prof.get("birth") or "").strip()
    if not b:
        return None
    d = parse_date(b)
    if d is None and len(b) >= 4 and b[:4].isdigit():
        d = date(int(b[:4]), 12, 31)
    if d is None:
        return None
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


# ---------------- 대화형 설문 ----------------
def _ask(q, default=None, kind=str, choices=None):
    hint = f" [{default}]" if default not in (None, "") else ""
    if choices:
        hint = f" ({'/'.join(choices)})" + hint
    while True:
        a = input(f"• {q}{hint}: ").strip()
        if not a:
            return default
        if choices and a not in choices:
            print(f"  → {', '.join(choices)} 중에서 골라 주세요")
            continue
        try:
            if kind is bool:
                if a.lower() in ("y", "yes", "예", "네", "o", "1", "true"):
                    return True
                if a.lower() in ("n", "no", "아니오", "아니요", "x", "0", "false"):
                    return False
                raise ValueError
            if kind is int:
                return int(a.replace(",", ""))
            if kind is list:
                return [x.strip() for x in a.replace("/", ",").split(",") if x.strip()]
            return a
        except ValueError:
            print("  → 형식을 다시 확인해 주세요")


def run_survey():
    cur = load() if (PROFILE_FILE.exists() or os.environ.get("PROFILE_JSON")) else dict(DEFAULT)
    print("\n🏠 청약 알리미 설문 — 엔터를 누르면 [기본값]을 씁니다\n")
    p = dict(cur)
    p["birth"] = _ask("생년월일 (YYYY-MM-DD, 연도만도 가능)", cur["birth"])
    p["marital"] = _ask("혼인 상태", cur["marital"], choices=["미혼", "예비신혼", "신혼", "기혼"])
    if p["marital"] != "미혼":
        p["children"] = _ask("미성년 자녀 수", cur["children"], int)
        p["newborn"] = _ask("2세 미만 자녀가 있거나 임신 중인가요? (y/n)", cur["newborn"], bool)
    p["single_parent"] = _ask("한부모 가정인가요? (y/n)", cur["single_parent"], bool)
    p["homeless"] = _ask("본인 명의 집이 없나요? (y/n)", cur["homeless"], bool)
    p["ever_owned"] = _ask("과거에 집을 가진 적이 있나요? (y/n)", cur["ever_owned"], bool)
    p["household"] = _ask("세대 구성", cur["household"], choices=["단독세대주", "부모님세대원", "기타"])
    if p["household"] != "단독세대주":
        p["household_homeless"] = _ask("같은 세대(주민등록) 모두 집이 없나요? (y/n)",
                                       cur["household_homeless"], bool)
    else:
        p["household_homeless"] = p["homeless"]
    p["employed"] = _ask("직장인/소득활동 중인가요? (y/n)", cur["employed"], bool)
    p["student"] = _ask("대학생·대학원생인가요? (y/n)", cur["student"], bool)
    p["monthly_income"] = _ask("세전 월소득 (만원)", cur["monthly_income"], int)
    p["assets"] = _ask("총자산 (만원, 예금·전세보증금 포함)", cur["assets"], int)
    p["car"] = _ask("자동차 가액 (만원, 없으면 0)", cur["car"], int)
    p["low_income"] = _ask("기초생활수급·차상위인가요? (y/n)", cur["low_income"], bool)
    p["disabled"] = _ask("장애인 등록이 되어 있나요? (y/n)", cur["disabled"], bool)
    p["artist_or_startup"] = _ask("예술인 또는 청년창업가인가요? (y/n)", cur["artist_or_startup"], bool)
    p["account_years"] = _ask("청약통장 가입 기간 (년)", cur["account_years"], int)
    p["account_payments"] = _ask("청약통장 납입 횟수", cur["account_payments"], int)
    p["residence"] = _ask("현재 거주 시도 (예: 서울)", cur["residence"])
    p["residence_since"] = _ask("전입 시점 (YYYY-MM)", cur["residence_since"])
    p["regions"] = _ask("알림 받을 지역 (쉼표로, 예: 서울,경기,인천)", ",".join(cur["regions"]), list)
    if isinstance(p["regions"], str):
        p["regions"] = [x.strip() for x in p["regions"].split(",") if x.strip()]
    print("\n관심 유형 (y/n)")
    p["want"] = {k: _ask(f"  {k}", v, bool) for k, v in cur["want"].items()}
    p["account_mode"] = _ask("빼고 받을 공고 — 상관없음=다 받고 통장 사용 여부만 표시, "
                             "가입만까지=당첨 시 통장이 소멸되는 분양은 빼기, 불필요만=통장 쓰는 건 전부 빼기",
                             cur.get("account_mode", "상관없음"), choices=["불필요만", "가입만까지", "상관없음"])
    p["min_level"] = _ask("알림 범위", cur["min_level"], choices=["추천", "확인"])
    p["remind_days"] = _ask("접수 며칠 전에 리마인더?", cur["remind_days"], int)
    PROFILE_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 저장: {PROFILE_FILE.name}")
    print("GitHub Actions 로 돌릴 거면 아래 한 줄을 Secret 'PROFILE_JSON' 에 넣으세요:\n")
    print(json.dumps(p, ensure_ascii=False, separators=(",", ":")))
    return p
