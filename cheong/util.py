"""날짜 파싱, 재시도 HTTP, 지역명 정규화."""
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (cheongyak-alert; personal use)"


def today_kst() -> date:
    return datetime.now(KST).date()


_DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]?\s*(\d{1,2})\s*[.\-/월]?\s*(\d{1,2})")


def parse_date(s):
    """'2026-10-13', '2026.10.13', '20261013', '2026년 10월 13일' → date. 실패 시 None."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    m = _DATE_RE.search(str(s))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def safe_http_error(error, url):
    """인증정보가 섞일 수 있는 원본 예외 대신 진단용 종류·호스트·상태만 남긴다."""
    host = urlsplit(url).hostname or "HTTP endpoint"
    status = f" HTTP {error.response.status_code}" if error.response is not None else ""
    return requests.exceptions.RequestException(f"{type(error).__name__}: {host}{status}")


def _request(method, url, params=None, data=None, timeout=30, retries=3, backoff=3, label="http"):
    """재시도 HTTP. 공공데이터포털은 일시적 5xx·타임아웃이 잦다."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.request(method, url, params=params, data=data, timeout=timeout,
                                 headers={"User-Agent": UA})
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            # requests 예외 문자열은 URL 쿼리(API 키)·인증정보를 포함할 수 있다.
            # 재시도 로그뿐 아니라 호출자의 오류 로그/traceback도 안전하게 만든다.
            last = safe_http_error(e, url)
            if attempt < retries:
                print(f"[{label}] 재시도 {attempt}/{retries}: {last}")
                time.sleep(backoff * attempt)
    raise last from None


def get(url, params=None, timeout=30, retries=3, backoff=3, label="http"):
    return _request("GET", url, params=params, timeout=timeout, retries=retries, backoff=backoff, label=label)


def post(url, data=None, timeout=30, retries=3, backoff=3, label="http"):
    return _request("POST", url, data=data, timeout=timeout, retries=retries, backoff=backoff, label=label)


SIDO = {
    "서울": ("서울",), "경기": ("경기",), "인천": ("인천",), "부산": ("부산",),
    "대구": ("대구",), "광주": ("광주",), "대전": ("대전",), "울산": ("울산",),
    "세종": ("세종",), "강원": ("강원",), "충북": ("충북", "충청북"),
    "충남": ("충남", "충청남"), "전북": ("전북", "전라북"), "전남": ("전남", "전라남"),
    "경북": ("경북", "경상북"), "경남": ("경남", "경상남"), "제주": ("제주",),
}


def to_sido(text: str) -> str:
    """주소·지역 문자열에서 시도 약칭을 찾는다. 못 찾으면 ''."""
    t = (text or "").strip()
    for short, keys in SIDO.items():
        if any(t.startswith(k) for k in keys):
            return short
    for short, keys in SIDO.items():
        if any(k in t for k in keys):
            return short
    return ""
