"""청약 자격 사전 체커 (참고용 · 공식 판정 아님).

사용자 프로필(config 의 '청약' 블록)로 특별공급 유형별 해당 가능성과
가점(만 30세 규칙 반영)을 규칙 기반으로 스크리닝한다.

⚠️ 한계: 실제 자격은 청약홈이 정부 기록으로 자동 판정한다. 소득기준·지역 거주요건·
자산요건·청약통장 납입 인정 등은 유형/연도/지역마다 다르고 매년 바뀐다.
따라서 이 결과는 '놓치지 않게 걸러주는 참고'이며, 구조적으로 불가능한 것만 '불가',
문턱값에 의존하는 것은 '확인필요'로 표기한다. 최종 확인·신청은 본인이 청약홈에서.
"""
from datetime import date

CAVEAT = ("참고용 규칙기반 스크리닝입니다. 소득·자산·지역 거주요건·통장 납입 인정 등은 "
          "유형/연도/지역마다 다르고, 과거 주택 소유·처분 이력이 있으면 무주택기간이 실제와 다를 수 있습니다. "
          "최종 자격 판정은 청약홈·공고문에서 본인이 확인해야 합니다.")


def _plus_years(d, years):
    """윤년 2/29 방어: 만 N세 도래일 계산(평년이면 2/28로)."""
    try:
        return date(d.year + years, d.month, d.day)
    except ValueError:
        return date(d.year + years, d.month, 28)


def _parse_ym(s):
    """생년월일/전입일 문자열을 date로. YYYY-MM-DD·YYYY-MM·YYMMDD·YYYYMMDD 지원. 실패 None."""
    if not s:
        return None
    s = str(s).strip().replace(".", "-").replace("/", "-")
    try:
        if "-" in s:  # 구분자 있으면 YYYY-MM-DD / YYYY-MM
            parts = s.split("-")
            if len(parts) >= 3:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            if len(parts) == 2:
                return date(int(parts[0]), int(parts[1]), 1)
            return None
        if len(s) == 6:  # YYMMDD (00~30 → 2000년대)
            yy = int(s[:2])
            year = 2000 + yy if yy <= 30 else 1900 + yy
            return date(year, int(s[2:4]), int(s[4:6]))
        if len(s) == 8:  # YYYYMMDD
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None
    return None


def _age(birth, today=None):
    today = today or date.today()
    if not birth:
        return None
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _years_between(d, today=None):
    today = today or date.today()
    if not d:
        return None
    return round((today - d).days / 365.25, 2)


def _is_single(profile):
    """미혼 여부. 혼인상태='미혼' 또는 혼인신고일 없음."""
    status = str(profile.get("혼인상태", "")).strip()
    if status in ("미혼", "single", ""):
        return not profile.get("혼인신고일")
    return False


def no_house_counted_years(profile, today=None):
    """가점 산정용 무주택기간(년). 무주택기간은 만 30세부터, 기혼은 혼인신고일부터 카운트.

    - 유주택이면 0
    - 미혼·만30세 미만이면 0 (평생 무주택이어도 가점상 0)
    - 미혼·만30세 이상이면 (오늘 - 만30세)
    - 기혼이면 (오늘 - max(만30세, 혼인신고일))
    """
    today = today or date.today()
    if not profile.get("무주택", True):
        return 0.0
    birth = _parse_ym(profile.get("생년월일"))
    if not birth:
        return None  # 정보부족
    thirty = _plus_years(birth, 30)
    marriage = _parse_ym(profile.get("혼인신고일"))
    # 산정시작 = 만30세 도래일. 단 만30세 이전에 혼인했으면 혼인신고일부터.
    start = min(thirty, marriage) if marriage else thirty
    if today <= start:
        return 0.0
    return round((today - start).days / 365.25, 2)


def _no_house_applicable(profile, today=None):
    """무주택 가점 산정 대상 여부: 무주택 & (만30세 이상 또는 기혼)."""
    today = today or date.today()
    if not profile.get("무주택", True):
        return False
    if not _is_single(profile) or profile.get("혼인신고일"):
        return True
    age = _age(_parse_ym(profile.get("생년월일")), today)
    return age is not None and age >= 30


def gajeom(profile, today=None):
    """만30세 규칙을 반영한 실제 청약가점을 계산해 반환(cheong.gajeom 위임).

    무주택 가점 산정 대상이 아니면(만30세 미만 미혼/유주택) 무주택 항목을 0점으로 보정한다
    ('무주택 1년 미만 2점'과 '산정 제외 0점'은 다르기 때문).
    """
    from .gajeom import calc_gajeom
    today = today or date.today()
    nh = no_house_counted_years(profile, today) or 0.0
    r = calc_gajeom(nh, profile.get("부양가족", 0) or 0, profile.get("청약통장기간", 0) or 0)
    if not _no_house_applicable(profile, today):
        diff = r["breakdown"]["no_house"]
        r["breakdown"]["no_house"] = 0
        r["total"] = r["total"] - diff
        if isinstance(r.get("detail"), dict):
            r["detail"]["no_house"] = "만 30세 미만 미혼(또는 유주택) → 무주택 가점 산정 제외(0점)"
    return r


def _v(verdict, reason, checks=None):
    return {"판정": verdict, "근거": reason, "확인필요": checks or []}


def check_eligibility(profile, record=None, today=None):
    """특별공급 유형별 + 일반공급 + 지역 스크리닝 결과 dict 반환."""
    today = today or date.today()
    birth = _parse_ym(profile.get("생년월일"))
    age = _age(birth, today)
    single = _is_single(profile)
    kids = int(profile.get("자녀수", 0) or 0)
    no_house = bool(profile.get("무주택", True))
    first_home = bool(profile.get("생애최초", False))
    parents_care = bool(profile.get("노부모부양", False))
    account_y = profile.get("청약통장기간", 0) or 0
    move_in = _parse_ym(profile.get("거주전입일"))
    reside_y = _years_between(move_in, today)

    sp = []  # 특별공급 유형별 판정

    # 청년 특별공급(뉴:홈 등 공공): 만19~39 미혼 무주택 + 소득/자산 요건
    if age is None:
        sp.append({"유형": "청년", **_v("확인필요", "생년월일 정보 필요")})
    elif 19 <= age <= 39 and single and no_house:
        sp.append({"유형": "청년", **_v(
            "해당가능", f"만 {age}세·미혼·무주택 → 청년 특공 대상 구조 충족",
            ["소득/자산 요건(유형별 상이)", "청약통장 가입기간·납입 인정", "공공분양(뉴:홈 등)에 주로 존재"])})
    else:
        why = []
        if age is not None and not (19 <= age <= 39):
            why.append(f"나이 만{age}세(대상 19~39 벗어남)")
        if not single:
            why.append("미혼 아님")
        if not no_house:
            why.append("무주택 아님")
        sp.append({"유형": "청년", **_v("불가", " / ".join(why) or "요건 미충족")})

    # 생애최초 특별공급: 무주택 + 생애최초 + 소득요건 (미혼 1인가구는 공공 추첨 유형 위주)
    if no_house and first_home:
        checks = ["소득요건(도시근로자 월평균소득 대비)", "청약통장 요건", "세대주 여부"]
        note = "무주택·생애최초 구조는 충족"
        if single:
            note += " (미혼 1인가구는 공공분양 추첨 유형 등으로 제한적 → 유형 확인 필수)"
        sp.append({"유형": "생애최초", **_v("확인필요", note, checks)})
    else:
        sp.append({"유형": "생애최초", **_v(
            "불가", "무주택+생애최초 요건 미충족" if not (no_house and first_home) else "요건 미충족")})

    # 신혼부부: 혼인 7년 이내
    if single:
        sp.append({"유형": "신혼부부", **_v("불가", "미혼(혼인 7년 이내 세대 대상)")})
    else:
        sp.append({"유형": "신혼부부", **_v("확인필요", "혼인기간 7년 이내/소득/자녀 요건 확인",
                                          ["혼인신고일 7년 이내", "소득요건"])})

    # 다자녀: 미성년 자녀 2명 이상(개편)/3명
    if kids >= 2:
        sp.append({"유형": "다자녀", **_v("확인필요", f"미성년 자녀 {kids}명 → 요건 확인",
                                        ["자녀 수 기준(2명/3명, 공고별)", "소득요건"])})
    else:
        sp.append({"유형": "다자녀", **_v("불가", f"미성년 자녀 {kids}명(2명 이상 필요)")})

    # 노부모부양: 65세+ 직계존속 3년+ 부양 세대주
    sp.append({"유형": "노부모부양", **_v(
        "확인필요" if parents_care else "불가",
        "노부모부양 세대주 요건 확인" if parents_care else "해당 없음(65세+ 직계존속 3년+ 부양 세대주 아님)")})

    # 일반공급 가점제 상황
    g = gajeom(profile, today)
    nh = no_house_counted_years(profile, today)
    gajeom_note = f"청약가점 약 {g['total']}점/84 (무주택 {g['breakdown']['no_house']}·부양 {g['breakdown']['dependents']}·통장 {g['breakdown']['account']})"
    if nh == 0.0 and single and age is not None and age < 30:
        gajeom_note += " — 만30세 미만 미혼이라 무주택 가점 0. 가점제(민영 인기단지)보다 추첨제·청년특공이 현실적."
    general = {
        "가점": gajeom_note,
        "통장기간_1순위": (f"가입기간 {account_y}년 → 1순위 가입기간 요건 충족 가능(지역별 기준 상이, 공고 확인)"
                       if account_y and account_y >= 2
                       else "가입기간 짧아 1순위 요건 확인필요(지역별 상이)"),
        "확인필요": ["국민주택은 납입 횟수·인정금액이 순위에 중요(납입 불성실 시 불리)"],
    }

    # 지역 우선공급
    region = {
        "거주지": profile.get("거주지역", "미상"),
        "거주기간": (f"약 {reside_y}년" if reside_y is not None else "미상"),
    }
    if reside_y is not None and reside_y < 1:
        region["해당지역우선"] = "미충족 가능 — 해당지역 우선공급은 통상 일정 거주기간 필요(대개 1~2년). 현재 기타지역 물량 위주일 수 있음. 공고문 확인."
    else:
        region["해당지역우선"] = "거주기간 요건 확인필요(지역/공고별 상이)"

    return {
        "나이": age,
        "무주택산정기간": nh,
        "가점": g,
        "특별공급": sp,
        "일반공급": general,
        "지역": region,
        "caveat": CAVEAT,
    }


def summarize(result):
    """check_eligibility 결과를 사람이 읽는 텍스트로."""
    lines = []
    age = result.get("나이")
    lines.append(f"■ 청약 자격 사전 체크 (만 {age}세)" if age is not None else "■ 청약 자격 사전 체크")
    g = result["가점"]
    lines.append(f"· 예상 청약가점: {g['total']}/84  "
                 f"(무주택 {g['breakdown']['no_house']} · 부양 {g['breakdown']['dependents']} · 통장 {g['breakdown']['account']})")
    lines.append("")
    lines.append("[특별공급 스크리닝]")
    icon = {"해당가능": "✅", "확인필요": "🟡", "불가": "⛔"}
    for s in result["특별공급"]:
        head = f"  {icon.get(s['판정'], '·')} {s['유형']}: {s['판정']} — {s['근거']}"
        lines.append(head)
        for c in s.get("확인필요", []):
            lines.append(f"       · 확인: {c}")
    lines.append("")
    lines.append("[일반공급]")
    lines.append(f"  · {result['일반공급']['가점']}")
    lines.append(f"  · 1순위: {result['일반공급']['통장기간_1순위']}")
    for c in result["일반공급"].get("확인필요", []):
        lines.append(f"  · 확인: {c}")
    lines.append("")
    lines.append("[지역]")
    r = result["지역"]
    lines.append(f"  · {r['거주지']} 거주 {r['거주기간']} → {r['해당지역우선']}")
    lines.append("")
    lines.append(f"⚠️ {result['caveat']}")
    return "\n".join(lines)
