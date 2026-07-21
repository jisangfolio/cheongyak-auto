"""공고별 '지원 가치' 필터.

목표: 사용자가 **구조적으로 지원 불가한 공고**(예: 신혼희망타운=미혼 불가)는 걸러내고,
당첨 확률이 낮아도 **지원 가능한 경로가 하나라도 있으면 살린다**(추첨제 물량 등).

한계(정직): 청약홈의 특별공급 유형별 세대수 상세 API는 공개가 제한적이라(별도 서비스),
여기서는 공고명·주택유형 휴리스틱으로 판정한다. 예를 들어 '신혼희망타운'은 전용이라
이름으로 확실히 배제되지만, 일반+특별공급이 혼합된 단지의 정확한 물량 구성은 공고문 확인이 필요하다.
"""
from . import eligibility

CAVEAT = ("공고명·유형 기반 휴리스틱 필터입니다. 특별공급 유형별 세대수 구성은 "
          "청약홈 공고문에서 확인하세요. 구조적으로 불가한 경우만 제외하고, "
          "확률이 낮아도 지원 경로가 있으면 유지합니다.")

# 미혼이면 구조적으로 지원 불가한 '전용' 공고 키워드(전용성이 확실한 것만 보수적으로)
_SINGLE_BLOCKED = ("신혼희망타운",)


def applicability(record, profile):
    """record(공고) + profile(사용자) → 지원가치 판정 dict.

    반환: {worth: bool, verdict, reason, paths: [지원가능경로], note, caveat}
    """
    name = str(record.get("name", ""))
    htype = str(record.get("type", ""))
    no_house = bool(profile.get("무주택", True))
    single = eligibility._is_single(profile)

    # 1) 무주택 요건 — 유주택이면 대부분 청약 유형에서 구조적 배제
    if not no_house:
        return {
            "worth": False, "verdict": "지원불가",
            "reason": "무주택 요건 미충족(대부분 청약 유형이 무주택 세대 대상)",
            "paths": [], "note": "", "caveat": CAVEAT,
        }

    # 2) 미혼인데 신혼 전용 단지(신혼희망타운 등) → 구조적 불가
    #    (예비신혼부부·한부모는 예외지만 프로필에 해당 필드가 없어 순수 미혼 기준으로 판정)
    if single and any(k in name for k in _SINGLE_BLOCKED):
        return {
            "worth": False, "verdict": "지원불가(구조적)",
            "reason": "신혼희망타운=신혼부부·예비신혼·한부모 전용 → (예비신혼·한부모 아닌) 미혼은 지원 경로 없음",
            "paths": [], "note": "", "caveat": CAVEAT,
        }

    # 임대주택(국민임대·행복주택·분양전환임대·전세/매입임대)은 분양 청약과 구조가 다르다.
    is_rental = ("임대" in name) or ("행복주택" in name)

    # 신혼 전용 임대(신혼부부 매입/전세임대 등) → 미혼 구조적 불가
    if single and is_rental and "신혼" in name:
        return {
            "worth": False, "verdict": "지원불가(구조적)",
            "reason": "신혼부부 전용 임대 → (예비신혼 아닌) 미혼은 지원 경로 없음",
            "paths": [], "note": "", "caveat": CAVEAT,
        }

    # 3) 임대주택 — 계층(고령자/신혼/청년/일반)별로 사용자에 맞춰 판정
    if is_rental:
        return _rental_verdict(name, profile)

    # 4) 분양주택 — 지원 가능 경로 산출(확률 낮아도 유지)
    elig = eligibility.check_eligibility(profile)
    verdicts = {s["유형"]: s["판정"] for s in elig["특별공급"]}
    g = elig["가점"]["total"]
    paths = []

    if "국민" in htype or "공공" in htype:
        paths.append("일반공급(순차제 — 통장 납입 인정액·횟수 중요)")
    else:  # 민영 등
        paths.append("일반공급(가점제 + 지역·면적별 추첨 물량 — 공고 확인)")

    if verdicts.get("청년") == "해당가능":
        paths.append("청년 특별공급(공공분양) 가능성")
    if verdicts.get("생애최초") == "확인필요":
        paths.append("생애최초 특별공급(소득/유형 확인)")
    if verdicts.get("신혼부부") == "확인필요":  # 기혼 프로필용
        paths.append("신혼부부 특별공급(요건 확인)")

    note = ""
    if g < 30:
        note = (f"청약가점 {g}점으로 가점제 당첨은 어렵다 → 추첨제·특별공급 경로 위주로 노려라"
                "(확률은 낮아도 지원 가치는 있음).")

    return {
        "worth": True, "verdict": "지원가치있음",
        "reason": f"지원 가능한 경로 {len(paths)}개",
        "paths": paths, "note": note, "caveat": CAVEAT,
    }


def _rental_verdict(name, profile):
    """LH 임대 공고를 계층(고령자/신혼/청년/일반)별로 사용자 나이·혼인에 맞춰 판정."""
    from . import eligibility
    age = eligibility._age(eligibility._parse_ym(profile.get("생년월일")))
    single = eligibility._is_single(profile)

    def block(reason):
        return {"worth": False, "verdict": "지원불가(구조적)", "reason": reason,
                "paths": [], "note": "", "caveat": CAVEAT}

    def ok(path, note=""):
        return {"worth": True, "verdict": "지원가치있음(임대)", "reason": "임대 지원 경로 존재",
                "paths": [path], "note": note, "caveat": CAVEAT}

    young = age is not None and 19 <= age <= 39

    # 행복주택·통합공공임대 = 다계층 혼합(청년 계층 포함). '고령자/신혼' 단어가 이름에
    # 섞여 있어도 청년 적격자를 통째 배제하지 않도록 먼저 처리한다.
    if "행복주택" in name or "통합공공임대" in name:
        if young:
            return ok("행복주택/통합공공임대 — 청년 계층 지원 가능(소득·자산 요건 확인)")
        return ok("행복주택/통합공공임대 — 계층 혼합. 대상 계층·소득기준 공고 확인")

    # 고령자복지주택(전용 상품) → 만65세 이상. '고령자' 단어만이 아니라 전용상품명으로 한정.
    if "고령자복지주택" in name and (age is None or age < 65):
        return block(f"고령자복지주택=만65세 이상 대상 → 해당 없음(만 {age}세)"
                     if age is not None else "고령자복지주택=만65세 이상 대상")

    # 청년 임대 → 만19~39세(군복무 시 최대 6년 차감 예외 존재)
    if "청년" in name:
        if young:
            return ok("청년 임대 — 만19~39·미혼·무주택 대상(소득·자산 요건 확인)")
        if age is not None and age <= 45:  # 상한 근처는 군복무 차감 예외 가능 → 확인
            return ok("청년 임대(만19~39, 군복무 차감 시 최대 45세) — 나이 요건 확인 필요")
        return block(f"청년 임대(만19~39 대상) → 나이 만{age}세 범위 밖"
                     if age is not None else "청년 임대(만19~39 대상)")

    # 신혼(부부) 전용 임대(행복/통합 아님) → 미혼 불가
    if single and "신혼" in name:
        return block("신혼(부부) 전용 임대 → (예비신혼 아닌) 미혼은 지원 경로 없음")

    # 영구임대 → 생계·의료급여수급자·국가유공자 등 사회보호계층 전용
    if "영구임대" in name:
        return ok("영구임대 — 생계·의료급여수급자·국가유공자·차상위 등 대상",
                  "수급자·특례계층이 아니면(단순 근로소득 저소득으론) 지원 대상 아님 → 자격 확인 필수")

    # 국민임대·공공임대·전세/매입임대·기타 → 소득·자산 상한 계층 심사(상한 초과 시 불가)
    return ok("임대주택 — 소득·자산 요건 심사(계층별, 소득상한 초과 시 불가). "
              "대상 계층·소득기준은 공고 확인")


def one_liner(record, profile):
    """이메일/목록용 한 줄 요약."""
    v = applicability(record, profile)
    if not v["worth"]:
        return f"⛔ 제외 — {v['reason']}"
    return "▸ 지원경로: " + " / ".join(v["paths"])
