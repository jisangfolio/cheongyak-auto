# 청약 알리미 v2 (cheongyak-auto)

설문으로 받은 **내 조건**(나이·혼인·무주택·세대·소득·통장·지역)에 맞는 청약 공고만 골라
**디스코드**로 알려준다. GitHub Actions 에서 하루 2번(08:47 / 17:47 KST) 돌아가므로 맥이 꺼져 있어도 된다.

> 알림까지만 자동화한다. 실제 신청(인증서 로그인·자격 확인·제출)은 직접 한다.
> 판정은 공고 제목·유형 기반이라 **최종 자격은 반드시 공고문으로 확인**할 것.

## 무엇을 보나

| 수집처 | 내용 | 방식 |
|---|---|---|
| 청약홈 | 민영·공공 APT, 무순위(줍줍), 오피스텔·민간임대, 공공지원 민간임대 | 공식 오픈API |
| LH | 임대주택, 주거복지(매입임대·전세임대·든든전세) | 공식 오픈API (목록+상세) |
| SH | 공공임대·공공분양 | 서울주거포털 목록 |
| 청년안심주택 | 공공·민간 청년안심주택 | 서울시 모집공고 게시판 |

## 판정 (추천 / 확인 / 제외)

- **제외**: 구조적으로 불가한 것만 — 관심지역 밖, 신혼 전용인데 미혼, 고령자·장애인·수급자·대학생·예술인 전용, 유주택 등
- **추천**: 대상 계층에 확실히 해당 — 청년 대상(만 19~39), 든든전세, 행복주택 청년, 공공분양 청년특공 구조 등
- **확인**: 소득·자산·순위 기준을 공고문에서 봐야 하는 것 (기본 설정은 추천+확인 모두 알림)
- 당첨자 발표·서류심사·계약 안내 같은 **후속 안내는 무시**

### 청약통장 표시
모든 알림 맨 위에 이 공고가 청약통장을 쓰는지 표시한다.

| 표시 | 뜻 | 예 |
|---|---|---|
| 🟢 필요 없음 | 통장 없이 지원 | 매입·전세임대, 든든전세, 청년안심, 민간임대, 오피스텔, 무순위, 희망하우징 |
| 🔵 가입만 | 가입 사실만 확인, 당첨돼도 통장 유지 | 행복주택, 국민임대 |
| 🔴 사용 | 당첨되면 통장 효력 소멸 | 공공분양, 민영 APT, 신혼희망타운, 분양전환 공공임대 |
| ⚪ 확인 | 분류 불가 → 공고문 확인 | 장기전세, 재개발임대 등 |

일반 규정 기준이라 공고마다 예외가 있을 수 있다. 아예 빼고 싶으면 프로필의 `account_mode` 를
`가입만까지`(🔴 제외) 또는 `불필요만`(🔴·🔵 제외)로 바꾼다. 기본값 `상관없음` 은 표시만 한다.

## 알림 종류

- 📋 첫 실행: 지금 진행 중인 맞춤 공고 요약
- 🆕 새 맞춤 공고
- ⏰ 리마인더: 접수 시작 / 마감 N일 전 (같은 공고에 한 번씩, 짧은 접수는 한 번만)
- ⚠️ 어떤 수집처가 3회 연속 0건이면 경고, ❌ 실행 실패 시 링크

## 설정 (처음 한 번, 15분)

### 1) 디스코드 웹훅
디스코드에서 개인 서버를 만들고 → 알림 받을 채널 ⚙️ → **연동** → **웹후크** → 새 웹후크 → **웹후크 URL 복사**.
폰 디스코드 앱에서 그 채널 알림을 "모든 메시지"로 해 두면 푸시가 온다.

### 2) 공공데이터포털 API 키 (무료, 보통 즉시 승인)
[data.go.kr](https://www.data.go.kr) 로그인 → 아래 3개 각각 **활용신청** → 마이페이지 → **일반 인증키(Decoding)** 복사
- 한국부동산원_청약홈 분양정보 조회 서비스 (15098547)
- 한국토지주택공사_분양임대공고문 조회 서비스 (15058530)
- 한국토지주택공사_분양임대공고별 상세정보 조회 서비스 (15057999)

키는 하나로 같다. LH 는 `LH_KEY` 를 비우면 `APPLYHOME_KEY` 를 그대로 쓴다.

### 3) 설문 → 프로필
```bash
pip install -r requirements.txt
python -m cheong setup        # 대화형 설문 → profile.json + Secret용 한 줄 JSON 출력
```

### 4) GitHub Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 값 |
|---|---|
| `DISCORD_WEBHOOK_URL` | 1)의 웹훅 URL |
| `PROFILE_JSON` | 3)에서 출력된 한 줄 JSON |
| `APPLYHOME_KEY` | 2)의 인증키(Decoding) |
| `LH_KEY` | (선택) 다른 키를 쓸 때만 |

### 5) 첫 실행
Actions → **청약 알리미** → Run workflow → `dry_run` 체크 → 로그 확인 → 이상 없으면 체크 해제하고 다시 실행.
이후는 매일 자동. 알림 이력은 `state/state.json` 으로 커밋된다(공고 id·날짜만, 개인정보 없음).

### 6) LH 는 Mac 에서 (선택)
GitHub Actions 는 해외 IP 라 LH API(`apis.data.go.kr`)가 접속 시간 초과로 막힌다.
그래서 Actions 는 `CHEONG_SKIP=lh` 로 LH 를 빼고, LH 는 Mac 의 launchd 가 매일 09:07·18:07 에 돌린다.
```bash
bash scripts/install-mac.sh            # 한 번만 (로그: ~/.cheongyak-auto/logs/mac-run.log)
```
macOS 는 launchd 작업이 Desktop·Documents 안을 못 읽게 막아서, 실행용 복사본을 `~/.cheongyak-auto` 에
clone 하고 `.env`·`profile.json` 을 복사해 거기서 돌린다(실행 때마다 `git pull`). 둘 중 하나를 바꾸면 다시 설치.
두 곳 모두 `state/state.json` 을 `python -m cheong.sync` 로 커밋하고, 동시에 push 해 충돌하면
양쪽 기록을 합친다(중복 알림 없음). Mac 이 꺼져 있던 시간은 깨어날 때 한 번 돈다.
수집처 고르기: `CHEONG_ONLY=lh` (이것만) / `CHEONG_SKIP=lh,sh` (이것 빼고).

## 로컬에서 쓰기
`.env` 파일에 위 값들을 `KEY=값` 으로 넣고:
```bash
python -m cheong test-discord   # 웹훅 테스트
python -m cheong preview        # 진행 중 공고 + 판정 이유(제외 포함) 보기
python -m cheong run --dry-run  # 보내지 않고 출력만
python -m cheong run            # 실제 알림
python -m unittest discover -s tests -t .   # 테스트(네트워크 불필요)
```

## 구조
```
cheong/
  sources/applyhome.py  청약홈 4개 엔드포인트
  sources/lh.py         LH 목록 + 상세(접수일·발표일·주소)
  sources/sh.py         서울주거포털 SH 임대·분양 표 + SH 홈페이지 공고 게시판(사회주택 등)
  sources/youth.py      청년안심주택 게시판(JSON) — 본문에서 마감일까지
  profile.py            설문 / 프로필 로드(PROFILE_JSON → profile.json)
  eligibility.py        추천·확인·제외 판정 규칙
  discord.py            웹훅 임베드
  state.py              알림 이력
  sync.py               state.json 커밋·push (충돌 시 합치기)
  main.py               CLI (setup / run / preview / test-discord)
config.yaml             수집처 on/off (비밀값 없음)
scripts/                Mac launchd (LH 담당) 설치·실행
.github/workflows/alert.yml
```

## 한계
- SH 목록엔 접수기간이 없어 게시일·발표일만 쓴다(접수일 리마인더 없음). 게시 21일 뒤엔 종료로 본다.
- 소득·자산 세부 기준은 공고문 PDF 안에 있어 자동 판정하지 않는다.
- LH 는 해외 IP 차단으로 Actions 에서 못 읽는다 → Mac 이 꺼져 있으면 그동안 LH 알림이 늦어진다.
- SH·청년안심은 HTML 파싱이라 사이트 개편 시 깨질 수 있다 → 0건 경고로 알 수 있다.

## License
MIT
