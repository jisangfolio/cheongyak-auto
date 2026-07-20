"""LLM 기반 청약 공고 브리핑 (Anthropic Claude SDK).

- 공고 record와 사용자 profile을 받아 한국어 브리핑 텍스트를 생성한다.
- anthropic 패키지와 API 키가 있으면 Claude로 요약/적합도 문단을 만든다.
- 패키지/키가 없거나 오류가 나면 record 필드만으로 만든 템플릿 요약을 반환한다.
실제 청약 자격 판정·당첨 여부는 사람이 직접 확인해야 하며, 확정적 보장 표현은 쓰지 않는다.
"""
import os

DEFAULT_MODEL = "claude-opus-4-8"


def _fmt_val(v):
    """빈 값은 '정보 없음'으로 표기 (템플릿/프롬프트 공용)."""
    if v is None:
        return "정보 없음"
    s = str(v).strip()
    return s if s else "정보 없음"


def _record_lines(record):
    """record dict 를 사람이 읽는 라인 목록으로 변환 (방어적으로 .get 사용)."""
    return [
        f"- 주택명: {_fmt_val(record.get('name'))}",
        f"- 지역: {_fmt_val(record.get('area'))}",
        f"- 주소: {_fmt_val(record.get('addr'))}",
        f"- 유형: {_fmt_val(record.get('type'))}",
        f"- 모집공고일: {_fmt_val(record.get('notice_de'))}",
        f"- 청약접수: {_fmt_val(record.get('begin'))} ~ {_fmt_val(record.get('end'))}",
        f"- 당첨발표: {_fmt_val(record.get('award'))}",
        f"- 공급세대: {_fmt_val(record.get('households'))}",
        f"- 링크: {_fmt_val(record.get('url'))}",
    ]


def _profile_lines(profile):
    """profile dict 를 사람이 읽는 라인 목록으로 변환. 있으면 청약가점도 포함."""
    if not profile:
        return ["- (사용자 정보 없음)"]
    lines = [
        f"- 무주택기간: {_fmt_val(profile.get('무주택기간'))}",
        f"- 부양가족: {_fmt_val(profile.get('부양가족'))}",
        f"- 청약통장기간: {_fmt_val(profile.get('청약통장기간'))}",
        f"- 희망지역: {_fmt_val(profile.get('희망지역'))}",
    ]
    # 청약가점은 있으면만 추가
    score = profile.get("청약가점")
    if score is not None and str(score).strip():
        lines.append(f"- 청약가점: {_fmt_val(score)}")
    return lines


def _template_brief(record, profile):
    """LLM 미사용 시 record/profile 필드만으로 만든 템플릿 요약 문자열."""
    lines = ["[LLM 미사용 - 템플릿]", ""]
    lines += ["■ 공고 정보"]
    lines += _record_lines(record)
    lines += ["", "■ 사용자 조건"]
    lines += _profile_lines(profile)
    lines += [
        "",
        "※ 위 접수 기간과 자격 요건을 직접 확인하세요. "
        "본 요약은 참고용이며 당첨을 보장하지 않습니다.",
    ]
    return "\n".join(lines)


def _build_prompt(record, profile):
    """Claude 에 보낼 한국어 프롬프트 구성."""
    record_block = "\n".join(_record_lines(record))
    profile_block = "\n".join(_profile_lines(profile))
    return (
        "당신은 한국 아파트 청약 공고를 사용자에게 안내하는 도우미입니다.\n"
        "아래 [공고 정보]와 [사용자 조건]을 바탕으로 한국어 브리핑을 작성하세요.\n\n"
        f"[공고 정보]\n{record_block}\n\n"
        f"[사용자 조건]\n{profile_block}\n\n"
        "다음 형식으로 작성하세요.\n"
        "1) 핵심 3줄 요약 (각 줄 앞에 '- ' 사용)\n"
        "2) 이어서 이 사용자 조건에서의 지원 적합도를 한 문단으로 서술하고, "
        "가능하면 해당될 만한 특별공급 유형 힌트(예: 생애최초, 신혼부부, 다자녀 등)를 포함하세요.\n\n"
        "주의: 확정적인 당첨 보장 표현은 절대 쓰지 마세요. "
        "정보가 부족하면 '직접 확인 필요'로 안내하세요."
    )


def _extract_text(msg):
    """messages.create 응답에서 type=='text' 블록의 .text 를 연결."""
    parts = []
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
    return "".join(parts).strip()


def brief_notice(record, profile, cfg):
    """공고 record + 사용자 profile 로 한국어 브리핑 텍스트를 반환.

    cfg 는 config.yaml 의 briefing 섹션 dict: {model, api_key, max_tokens}.
    anthropic 패키지와 api_key 가 있으면 Claude 로 브리핑을 생성하고,
    없거나 오류가 나면 템플릿 요약을 반환한다. 어떤 경우에도 예외를 던지지 않는다.
    """
    record = record or {}
    profile = profile or {}
    cfg = cfg or {}

    model = cfg.get("model") or DEFAULT_MODEL
    api_key = cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    try:
        max_tokens = int(cfg.get("max_tokens", 600))
    except (TypeError, ValueError):
        max_tokens = 600

    # 키가 없으면 곧바로 템플릿으로 폴백
    if not api_key:
        return _template_brief(record, profile)

    # anthropic 은 지연 import (패키지 없어도 모듈 import 는 성공해야 함)
    try:
        import anthropic
    except ImportError:
        return _template_brief(record, profile)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_prompt(record, profile)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(msg)
        if text:
            return text
        # 응답이 비면 템플릿으로 폴백
        return _template_brief(record, profile)
    except Exception:
        # API 오류·네트워크 오류 등 모든 예외는 삼키고 템플릿으로 폴백
        return _template_brief(record, profile)
