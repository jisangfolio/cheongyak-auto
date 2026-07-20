# 청약 알리미 컨테이너 이미지
# 기본 실행: 청약홈 APT 공고 감시(apt-watch) — 순수 오픈API 호출이라 브라우저 불필요
FROM python:3.12-slim

# 파이썬 런타임 기본 설정
#  - 캐시(.pyc) 미생성으로 이미지 슬림화
#  - 표준출력/에러 버퍼링 해제(로그 즉시 노출)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어 먼저(소스 변경 시 캐시 재사용) — requirements.txt만 복사 후 설치
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Playwright(브라우저)는 설치하지 않는다.
#  - apt-watch(아파트 청약)는 공공데이터포털 오픈API(requests)만 사용하므로 브라우저가 불필요하다.
#  - playwright install-deps / install 은 이미지를 수백 MB 이상 무겁게 만든다.
#  - 브라우저 자동입력(autofill) 등 Playwright가 필요한 기능을 컨테이너에서 쓰려면
#    별도의 mcr.microsoft.com/playwright 계열 베이스 이미지를 쓰는 것을 권장한다.

# 애플리케이션 소스 복사(.dockerignore 로 config/log/상태파일 등은 제외)
COPY . .

# config.yaml 은 이미지에 굽지 않는다(.dockerignore 로 제외).
#  - API 키·Gmail 앱비밀번호 등 비밀이 담기므로 런타임에 주입한다.
#  - 파일 마운트 예:
#      docker run --rm -v "$PWD/config.yaml:/app/config.yaml:ro" <image>
#  - 또는 코드가 환경변수 오버라이드를 지원한다면 -e 로 주입한다.
#      docker run --rm -e APPLYHOME_SERVICE_KEY=... <image>

# 기본 커맨드: 청약홈 아파트 공고 감시(새 공고/접수 임박 알림)
CMD ["python", "-m", "cheong.main", "apt-watch"]
