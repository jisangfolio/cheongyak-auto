# 청약 알리미 (cheongyak-auto)

청약홈(한국부동산원) 공식 오픈API로 **관심 지역의 아파트 청약 공고**를 감지해
**새 공고 · 청약접수 임박**을 이메일과 macOS 알림으로 보내주는 도구.

> ⚠️ 이 도구는 **알림까지만** 자동화한다. 실제 청약 신청(공동인증서 로그인·자격 판정·제출)은
> 자동화 대상이 아니며 사용자가 직접 한다. 잘못된 신청은 부적격 당첨 등 실제 불이익이 있으므로,
> "좋은 공고를 놓치지 않게 잡아주는 것"까지가 안전한 자동화의 경계다.

## 주요 기능
- 📡 청약홈 공식 오픈API(공공데이터포털)로 APT 분양 공고 조회
- 🔎 관심 지역 · 주택유형 필터
- 🆕 이전에 없던 **새 공고** 감지 (기준선 저장 방식)
- ⏰ **청약접수 시작 임박**(기본 D-3) 리마인더
- 📧 이메일(SMTP) + macOS 데스크톱 알림
- ⏱️ launchd로 매일 자동 실행

## 동작 원리
```
청약홈 오픈API  →  지역/유형 필터  →  새 공고·임박 판별  →  이메일/데스크톱 알림
  (odcloud)        (config.yaml)      (.seen 기준선)         (SMTP / osascript)
```
최초 실행은 현재 공고를 기준선으로 조용히 저장하고, 이후부터 '새 공고'만 알린다.

## 설치
```bash
git clone <this-repo> cheongyak-auto
cd cheongyak-auto
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium         # 폼자동입력(선택 기능)에만 필요
cp config.example.yaml config.yaml  # 이후 config.yaml 값 채우기
```

### API 키 발급 (무료)
1. [공공데이터포털](https://www.data.go.kr) 로그인
2. [한국부동산원_청약홈 분양정보 조회 서비스](https://www.data.go.kr/data/15098547/openapi.do) → **활용신청**(보통 즉시 자동승인)
3. 마이페이지 → 오픈API → **일반 인증키(Decoding)** 복사 → `config.yaml` 의 `service_key` 에 입력

### 이메일 알림 설정
`config.yaml` 의 `notify.email` 에 SMTP 정보 입력.
Gmail은 로그인 비밀번호가 아니라 **앱 비밀번호(16자리)**가 필요하다
(구글 계정 → 보안 → 2단계 인증 → 앱 비밀번호).

## 사용법
```bash
python3 -m cheong.main test-notify        # 알림 설정 점검
python3 -m cheong.main apt-watch          # 청약홈 확인 → 새 공고/임박 알림 + DB 반영
python3 -m cheong.main sync-db            # 관심지역 공고 전체를 DB에 적재(+seen 이관)
python3 -m cheong.main gajeom             # 청약가점 계산(config '청약' 값 사용)
python3 -m cheong.main brief <공고번호>    # LLM 공고 브리핑(키 없으면 템플릿 요약)
python3 -m cheong.main predict <공고번호>  # 당첨 가능성 휴리스틱 추정
streamlit run dashboard/app.py            # 웹 대시보드(공고 표 + 가점 계산기)
```
- `brief` 는 `config.yaml` 의 `briefing.api_key`(또는 `ANTHROPIC_API_KEY` 환경변수)가 있으면 Claude로 요약하고, 없으면 템플릿으로 폴백한다.
- `predict` 는 **규칙 기반 휴리스틱**이며 당첨을 보장하지 않는다(경쟁률 API 연동 시 정확도 향상).

## 매일 자동 실행 (macOS launchd)
```bash
cp com.example.cheongyak-auto.plist ~/Library/LaunchAgents/com.<본인id>.cheongyak-auto.plist
# plist 안의 python 경로 / 프로젝트 경로를 본인 환경에 맞게 수정한 뒤:
launchctl load -w ~/Library/LaunchAgents/com.<본인id>.cheongyak-auto.plist
launchctl start com.<본인id>.cheongyak-auto        # 즉시 1회 테스트
# 끄기:
launchctl unload ~/Library/LaunchAgents/com.<본인id>.cheongyak-auto.plist
```
※ 최초 실행 시 macOS가 Desktop 접근 허용을 물으면 '허용'. permission 에러가 나면
   프로젝트를 Desktop 밖(예: `~/cheongyak-auto`)으로 옮기면 해결된다.

## config.yaml 구조
```yaml
applyhome:
  service_key: "..."          # data.go.kr 일반 인증키(Decoding)
  regions: ["서울", "경기"]    # 공급지역명 부분일치
  house_types: []             # 비우면 전체 (예: ["민영","국민"])
  remind_days_before: 3       # 접수 시작 N일 전부터 임박 알림
notify:
  desktop: true
  email: { smtp_host, smtp_port, username, password, from_addr, to_addr }
```

## 자동 실행 (클라우드 · 맥 없이)
`.github/workflows/daily.yml` 이 매일 09:00(KST) GitHub Actions 러너에서 `apt-watch` 를 실행한다.
저장소 → Settings → Secrets and variables → Actions 에 아래를 등록:
`APPLYHOME_SERVICE_KEY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `NOTIFY_TO`, `ANTHROPIC_API_KEY`.

## 아키텍처
```
청약홈 오픈API ──▶ cheong/db.py(SQLite) ──▶ dashboard(Streamlit)
     │                    ▲  ▲
     │  apt-watch         │  └── cheong/gajeom.py(청약가점 84점)
     └── 이메일/알림 ─────┘      cheong/briefing.py(Claude 브리핑)
                                cheong/predict.py(당첨 휴리스틱)
                                cheong/competition.py(경쟁률 API)
```

## 로드맵
- [x] 경쟁률 API 클라이언트 (`cheong/competition.py`, 별도 활용신청 필요)
- [x] 청약가점 계산기 (`cheong/gajeom.py`, 84점 만점)
- [x] SQLite 적재 (`cheong/db.py`)
- [x] GitHub Actions 스케줄러 (`.github/workflows/daily.yml`)
- [x] Streamlit 대시보드 (`dashboard/app.py`)
- [x] LLM 공고 브리핑 (`cheong/briefing.py`) · 당첨 확률 휴리스틱 (`cheong/predict.py`)
- [ ] 경쟁률 실데이터 연동 후 예측 정확도 개선 · 커트라인 학습 모델
- [ ] Docker 배포 (`Dockerfile` 포함, 이미지 퍼블리시 예정)

## 부가 기능: 응모 폼 자동입력 (실험적)
`cheong/monitor.py`·`cheong/autofill.py` 는 아파트 청약이 아닌 일반 응모 이벤트용으로,
오픈 감지 후 폼을 자동 입력하다 캡차/본인인증이 감지되면 사람에게 넘긴다.
`python3 -m cheong.main watch <타겟> --autofill` 참고.

## 면책
- 대상 서비스의 이용약관을 준수할 책임은 사용자에게 있다.
- 본 도구는 정보 알림 목적이며, 청약 신청·당첨·자격에 대한 어떤 것도 보장하지 않는다.

## License
MIT
