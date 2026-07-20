"""한국 아파트 청약가점 계산기 (84점 만점).

가점제는 세 항목의 합으로 산정한다.
  · 무주택기간   : 최대 32점
  · 부양가족수   : 최대 35점
  · 청약통장 가입기간 : 최대 17점
실제 청약 자격판정(무주택 인정 기준·세대원 요건 등)은 사람이 청약홈에서 확인해야 하며,
본 계산기는 입력값을 표준 공식에 대입해 참고용 점수를 산출할 뿐이다.
"""
import math

MAX_TOTAL = 84
MAX_NO_HOUSE = 32
MAX_DEPENDENTS = 35
MAX_ACCOUNT = 17


def _no_house_points(years):
    """무주택기간 가점(최대 32점).

    1년 미만 = 2점, 이후 1년당 +2점 (1~2년 4점, 2~3년 6점, ..., 15년 이상 32점).
    공식: min(32, 2 * (floor(years) + 1)). 음수는 0점.
    """
    try:
        y = float(years)
    except (TypeError, ValueError):
        return 0, "무주택기간: 입력값을 해석할 수 없어 0점 처리."
    if y < 0:
        return 0, "무주택기간: 음수 입력이라 0점 처리."
    n = math.floor(y)
    points = min(MAX_NO_HOUSE, 2 * (n + 1))
    if points >= MAX_NO_HOUSE:
        detail = f"무주택기간: {y:g}년 → 15년 이상 구간으로 상한 {MAX_NO_HOUSE}점."
    elif n == 0:
        detail = f"무주택기간: {y:g}년(1년 미만) → 2점."
    else:
        detail = f"무주택기간: {y:g}년({n}~{n + 1}년 구간) → {points}점(1년당 2점)."
    return points, detail


def _dependents_points(dependents):
    """부양가족수 가점(최대 35점).

    0명 = 5점, 1명 = 10점, ..., 6명 이상 = 35점.
    공식: min(35, 5 * (dependents + 1)). 음수는 0명으로 방어.
    """
    try:
        d = int(dependents)
    except (TypeError, ValueError):
        return 0, "부양가족수: 입력값을 해석할 수 없어 0명(5점) 처리."
    if d < 0:
        d = 0
        note = "(음수 입력 → 0명으로 처리)"
    else:
        note = ""
    points = min(MAX_DEPENDENTS, 5 * (d + 1))
    if points >= MAX_DEPENDENTS:
        detail = f"부양가족수: {d}명 → 6명 이상 구간으로 상한 {MAX_DEPENDENTS}점.{note}"
    else:
        detail = f"부양가족수: {d}명 → {points}점(0명 5점 기준 1명당 5점).{note}"
    return points, detail


def _account_points(years):
    """청약통장 가입기간 가점(최대 17점).

    6개월 미만 = 1점, 6개월~1년 = 2점, 1~2년 = 3점, 이후 1년당 +1점, 15년 이상 = 17점.
    즉 years<0.5 → 1, 0.5<=years<1 → 2, 1<=years<2 → 3, ..., 15년 이상 → 17.
    음수는 0으로 방어.
    """
    try:
        y = float(years)
    except (TypeError, ValueError):
        return 0, "청약통장 가입기간: 입력값을 해석할 수 없어 0점 처리."
    if y < 0:
        return 0, "청약통장 가입기간: 음수 입력이라 0점 처리."
    if y < 0.5:
        points, seg = 1, "6개월 미만"
    elif y < 1:
        points, seg = 2, "6개월~1년"
    else:
        # 1년 이상: 1~2년 3점, 이후 1년당 +1점 (2~3년 4점, ...).
        points = 3 + (math.floor(y) - 1)
        points = min(MAX_ACCOUNT, points)
        n = math.floor(y)
        seg = f"{n}~{n + 1}년"
    if points >= MAX_ACCOUNT:
        detail = f"청약통장 가입기간: {y:g}년 → 15년 이상 구간으로 상한 {MAX_ACCOUNT}점."
    else:
        detail = f"청약통장 가입기간: {y:g}년({seg} 구간) → {points}점."
    return points, detail


def calc_gajeom(no_house_years, dependents, account_years):
    """청약가점(84점 만점)을 계산해 dict로 반환한다.

    인자
      no_house_years : 무주택기간(년, 실수 허용)
      dependents     : 부양가족수(명, 정수)
      account_years  : 청약통장 가입기간(년, 실수 허용)

    반환
      {
        "total": int,
        "max": 84,
        "breakdown": {"no_house": int, "dependents": int, "account": int},
        "detail": {"no_house": str, "dependents": str, "account": str},
      }
    """
    no_house_pt, no_house_detail = _no_house_points(no_house_years)
    dependents_pt, dependents_detail = _dependents_points(dependents)
    account_pt, account_detail = _account_points(account_years)

    total = no_house_pt + dependents_pt + account_pt
    # 이론상 상한을 넘을 수 없으나 방어적으로 한 번 더 캡.
    total = min(MAX_TOTAL, total)

    return {
        "total": total,
        "max": MAX_TOTAL,
        "breakdown": {
            "no_house": no_house_pt,
            "dependents": dependents_pt,
            "account": account_pt,
        },
        "detail": {
            "no_house": no_house_detail,
            "dependents": dependents_detail,
            "account": account_detail,
        },
    }
