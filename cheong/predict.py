"""당첨 가능성 '휴리스틱' 추정기.

⚠️ 이것은 학습된 예측 모델이 아니라, 경쟁률·공급세대·가점 커트라인을
투명한 규칙으로 조합한 '규칙 기반 추정'이다. 결과는 참고용이며 확정이 아니다.

estimate_chance(record, competition, my_gajeom) -> dict
  - record:      applyhome._record() 형태의 공고 dict (households 등)
  - competition: 경쟁률/신청건수 등을 담은 dict 또는 None
  - my_gajeom:   내 청약 가점(0~84) 또는 None
반환:
  {"label": "높음|보통|낮음|정보부족",
   "score": 0~100 int | None,
   "rationale": 한국어 설명,
   "method": "heuristic",
   "caveat": "학습된 예측모델이 아닌 규칙기반 추정"}
"""
import re

METHOD = "heuristic"
CAVEAT = "학습된 예측모델이 아닌 규칙기반 추정"

# 일반적인 청약 가점 커트라인 가정(지역·단지별로 편차가 크므로 어디까지나 가정치).
# 실제 커트라인은 청약홈 발표 자료로 확인해야 한다.
CUTOFF_HOT = 60      # 수도권 인기 단지: 60점대라도 안심하기 어려움
CUTOFF_NORMAL = 45   # 보통 단지: 40~50점대 가정의 중앙값


def _to_float(v):
    """문자열/숫자에서 float 하나를 방어적으로 뽑아낸다. 실패 시 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    # "12.5 : 1", "12.5대 1", "1,234", "45.6%" 등 다양한 표기를 방어적으로 처리
    s = s.replace(",", "")
    # ':' 또는 '대'(경쟁률 구분자) 앞부분만 사용
    for sep in (":", "대"):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _to_int(v):
    f = _to_float(v)
    if f is None:
        return None
    try:
        return int(round(f))
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_competition(competition):
    """competition dict에서 경쟁률(rate)과 공급세대(supply)를 방어적으로 추출.

    다양한 키 이름을 순서대로 시도한다. 못 찾으면 None.
    경쟁률은 '값이 낮을수록 유리'하다는 의미로 사용한다.
    """
    if not competition or not isinstance(competition, dict):
        return None, None

    rate = None
    for key in ("rate", "competition_rate", "competition", "경쟁률",
                "avg_rate", "ratio"):
        if key in competition:
            rate = _to_float(competition.get(key))
            if rate is not None:
                break

    # 경쟁률이 직접 없으면 신청건수/공급세대로 유추
    supply = None
    for key in ("households", "supply", "supply_count", "공급세대",
                "TOT_SUPLY_HSHLDCO", "units"):
        if key in competition:
            supply = _to_int(competition.get(key))
            if supply is not None:
                break

    if rate is None:
        applicants = None
        for key in ("applicants", "apply_count", "신청건수", "req_cnt", "requests"):
            if key in competition:
                applicants = _to_float(competition.get(key))
                if applicants is not None:
                    break
        if applicants is not None and supply and supply > 0:
            rate = applicants / supply

    return rate, supply


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def estimate_chance(record, competition=None, my_gajeom=None):
    """당첨 가능성을 규칙 기반으로 추정한다(확정 아님).

    로직(투명하게):
      1) 경쟁률이 낮을수록 점수를 올린다(경쟁률↓ = 유리).
      2) 공급세대가 많을수록 소폭 가산한다(세대↑ = 유리).
      3) 내 가점이 있으면 가정 커트라인과 비교해 가감한다.
    근거는 데이터가 부족하면 label='정보부족', score=None 으로 반환한다.
    """
    record = record or {}
    rationale_parts = []

    # --- 1) 경쟁률 / 공급세대 추출 --------------------------------------
    rate, supply = _extract_competition(competition)

    # record 쪽 공급세대도 백업으로 시도
    if supply is None:
        supply = _to_int(record.get("households"))

    # --- 데이터 충분성 판단 --------------------------------------------
    # 경쟁률도 없고 내 가점도 없으면 근거가 사실상 없음 → 정보부족
    if rate is None and my_gajeom is None:
        return {
            "label": "정보부족",
            "score": None,
            "rationale": (
                "경쟁률 정보와 내 청약 가점이 모두 없어 규칙 기반 추정이 어렵습니다. "
                "경쟁률(또는 신청건수/공급세대) 또는 가점 정보를 제공하면 대략적인 "
                "추정이 가능합니다."
            ),
            "method": METHOD,
            "caveat": CAVEAT,
        }

    # 기본 점수 50(중립)에서 출발
    score = 50.0

    # --- 2) 경쟁률 반영 -------------------------------------------------
    if rate is not None and rate >= 0:
        # 경쟁률 구간별 가감(낮을수록 유리). 완만한 계단식.
        if rate <= 1:
            score += 30
            comp_txt = "미달~1:1 수준으로 매우 낮음"
        elif rate <= 3:
            score += 18
            comp_txt = "3:1 이하로 낮은 편"
        elif rate <= 7:
            score += 6
            comp_txt = "3~7:1 수준의 보통"
        elif rate <= 20:
            score -= 10
            comp_txt = "7~20:1로 높은 편"
        else:
            score -= 22
            comp_txt = "20:1을 넘는 매우 높은 경쟁"
        rationale_parts.append(f"경쟁률 약 {rate:g}:1 → {comp_txt}")
    else:
        rationale_parts.append(
            "경쟁률 정보가 없어 가점 위주로만 추정합니다."
        )

    # --- 3) 공급세대 반영(많을수록 소폭 유리) ---------------------------
    if supply is not None and supply > 0:
        if supply >= 1000:
            score += 6
            sup_txt = "1,000세대 이상으로 물량이 많아 유리"
        elif supply >= 300:
            score += 3
            sup_txt = "300세대 이상으로 물량이 여유 있는 편"
        elif supply < 30:
            score -= 4
            sup_txt = "30세대 미만으로 소규모라 문이 좁음"
        else:
            sup_txt = "보통 규모"
        rationale_parts.append(f"공급 {supply:,}세대 → {sup_txt}")

    # --- 4) 내 가점 vs 커트라인 가정 -----------------------------------
    gajeom = _to_int(my_gajeom)
    if gajeom is not None:
        if gajeom < 0 or gajeom > 84:
            # 청약 가점 만점은 84점. 범위를 벗어나면 신뢰하지 않고 안내만.
            rationale_parts.append(
                f"입력한 가점({gajeom})이 유효 범위(0~84)를 벗어나 반영하지 않았습니다."
            )
        else:
            # 인기 단지 여부를 경쟁률로 대략 추정(높으면 인기 단지로 간주).
            hot = rate is not None and rate >= 10
            cutoff = CUTOFF_HOT if hot else CUTOFF_NORMAL
            diff = gajeom - cutoff
            # 커트라인 대비 ±에 비례해 가감(과도하지 않게 계수 1.2, 최대 ±24).
            adj = _clamp(diff * 1.2, -24, 24)
            score += adj
            zone = "인기 단지 가정(커트라인 60점대)" if hot else "보통 단지 가정(커트라인 40~50점대)"
            if diff >= 8:
                cut_txt = "가정 커트라인을 넉넉히 상회"
            elif diff >= 0:
                cut_txt = "가정 커트라인 근처"
            else:
                cut_txt = "가정 커트라인에 다소 못 미침"
            rationale_parts.append(
                f"내 가점 {gajeom}점 vs {zone} → {cut_txt}"
            )
    else:
        rationale_parts.append(
            "내 청약 가점 정보가 없어 커트라인 비교는 생략했습니다."
        )

    # --- 5) 라벨링 -----------------------------------------------------
    score = int(round(_clamp(score)))
    if score >= 66:
        label = "높음"
    elif score >= 40:
        label = "보통"
    else:
        label = "낮음"

    rationale = (
        " · ".join(rationale_parts)
        + f" ⇒ 종합 추정 '{label}'(참고 점수 {score}/100). "
        + "이 수치는 규칙 기반 대략치이며 실제 당첨을 보장하지 않습니다."
    )

    return {
        "label": label,
        "score": score,
        "rationale": rationale,
        "method": METHOD,
        "caveat": CAVEAT,
    }
