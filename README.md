# ThermoShift Hanium

ThermoShift는 실증 공간의 **센서 데이터 수집**, **HVAC 제어**, **전력 피드백 검증**, **baseline 대비 성능 비교**를 통해 에너지 사용량을 줄이면서 실내 환경 품질을 유지하는 한이음 프로젝트입니다.

> 목표: 공간별 환경 특성과 재실 상태를 반영해 냉난방/환기 제어 전략을 제안하고, 실제 baseline 대비 에너지·쾌적성 KPI 개선을 검증한다.

## 문제의식

- 냉난방은 공간 구조, 재실 패턴, 시간대, 사용자 체감에 따라 최적 운영 방식이 달라집니다.
- 단순 온도 기준 또는 수동 운전은 불필요한 전력 사용, 무재실 냉방, CO₂ 초과, 온도 이탈을 만들 수 있습니다.
- 소규모 공간에서도 적용 가능한 센서 기반 제어·검증 시스템이 필요합니다.
- 최종 결과물은 단순 대시보드가 아니라 **실제 데이터 수집 → 제어 로직 적용 → 전력/환경 KPI 비교**까지 이어지는 프로토타입을 지향합니다.

## 핵심 결과물

- 실증 공간 센서 데이터 수집: 온도, 습도, CO₂, 재실 여부/사용 시간, 전력 사용량 등
- HVAC 제어: IR 송신 모듈 또는 제어 가능한 방식으로 에어컨 ON/OFF, setpoint, mode control 검토
- 데이터 파이프라인: 센서 통신, 저장 구조, API 또는 로그 구조 설계
- 제어 로직: rule-based 제어, pre-cooling, setback, CO₂ 기준 환기 판단
- 대시보드: 실시간 상태, 제어 상태, 제어 로그, baseline 대비 비교, KPI 표시
- 검증: 자동제어 적용 후 baseline 대비 에너지 사용량과 환경 품질 지표 비교

## MVP 범위

### 1차 목표

- 실증 공간에서 baseline 데이터 3~4일 수집
- 센서 데이터 저장 구조 확정
- rule-based 제어 로직 구현
- 대시보드 뼈대 구현
- baseline 대비 KPI 비교 방식 정의
- 최종 발표용 시연 영상 확보

### 2차 목표

- setpoint / mode control 고도화
- 공간별 특성 반영 제어 전략
- 모형 제작 또는 더 설득력 있는 프로토타입 시연
- HMM, EKF, MPC 등 고도화 모델은 추후 검토 범위로 분리

## Baseline & KPI

초기 baseline은 자동제어를 적용하지 않은 상태에서 3~4일 정도 수집하는 것을 우선 가정합니다. 정확한 기간은 멘토님과 상의 후 확정합니다.

| KPI | 측정/정의 | 목표 예시 |
|---|---|---|
| 에너지 사용량 | 냉난방 전력 소비량 | baseline 대비 5~10% 절감 |
| 냉방 운전 시간 | 에어컨이 실제로 켜져 있던 시간 | 무재실 운전 시간 감소 |
| 온도 이탈 시간 | 목표 온도 범위를 벗어난 시간 | baseline 대비 20% 감소 |
| CO₂ 초과 시간 | CO₂ 기준값을 넘은 시간 | baseline 대비 20% 감소 |
| 제어 명령 성공률 | IR 명령 후 실제 에어컨 동작 여부 | 95% 이상 지향 |
| 데이터 수집 성공률 | 센서 데이터 정상 저장 비율 | 95% 이상 지향 |
| 재실 추정 정확도 | 재실/무재실 판단 정확도 | F1-score 0.80 이상 지향 |

## 팀 역할

### 기술 역할

| 역할 | 담당 | 담당 업무 |
|---|---|---|
| 하드웨어·센서·설치 | 최주하 | 센서 선정, Raspberry Pi/ESP32 연결, IR 송신 모듈, 스마트 플러그, 설치 위치 검토 |
| 데이터 파이프라인·BE | 조하늘 | 센서 데이터 수집, 통신 방식, DB 저장, API 또는 로그 구조 설계 |
| 제어·모델링 로직 | 김종민 | 재실 판단 로직, rule-based 제어, pre-cooling/setback 조건, HMM/EKF/MPC 추후 검토 |
| 대시보드·KPI 검증·FE | 박민서 | 실시간 화면, baseline 비교, KPI 계산, 결과 리포트, 발표자료 구조화 |

### 운영 역할

| 역할 | 담당 | 주요 업무 | 산출물 |
|---|---|---|---|
| 팀장 / 일정·멘토 커뮤니케이션 | 김종민 | 회의실 예약, 멘토님 연락, 회의 일정 조율, 월별 마일스톤 관리 | 월별 일정표, 멘토 회의 일정 |
| 회의록·문서 관리 | 박민서 | 회의록 작성, 결정사항 정리, 발표자료 취합, Google Drive/Notion 정리 | 회의록, To-do 리스트, 발표자료 초안 |
| 기자재·예산 관리 | 최주하 | 기자재 후보 정리, 구매 링크 정리, 예산 관리, 물품 보관 | 기자재 리스트, 구매표, 예산표 |
| 부팀장 / 공간·현장 운영 | 조하늘 | 실증공간 섭외, 설치 가능 조건 확인, 현장 관련 업무 총괄, HW 신청 일정 체크 | 공간 후보표, 설치 체크리스트 |

## 5월 15일 전까지 할 일

- [ ] 각자 담당 업무 세부 범위 확정
- [ ] 실증 공간 후보 선정 및 현장 확인/예약 방법 확인
- [ ] 에어컨 IR 제어 가능 여부 확인
- [ ] 센서 설치 위치 후보 정리
- [ ] 기자재 구매 리스트를 `확정` / `보류`로 분리
- [ ] 스마트 플러그 포함 1차 구매 후보 확정
- [ ] 데이터 흐름 및 시스템 구조 초안 확정
- [ ] 1차 제어 로직 범위 확정
- [ ] 대시보드 뼈대 설계
- [ ] 5~7월 3개월 계획 수립
- [ ] 멘토님께 드릴 정기회의 방식/질문 정리

## Repository 구조

```text
.
├── README.md
├── CONTRIBUTING.md
├── firmware/                    # ESP32 센서 노드 스케치
├── gateway/                     # 제어 두뇌: MQTT 수집 · 재실 추정 · HVAC 제어
│   ├── app/                     #   controller / occupancy_hmm / ir_adapter ...
│   └── config/                  #   config.example.yaml (로컬 config.yaml은 미커밋)
├── api/                         # FastAPI. 프론트용 데이터·제어 API
│   └── app/routers/             #   auth / rooms / devices / control / alerts / schedules
├── db/
│   ├── schema/schema.sql        # 통합 SQLite 스키마 (단일 관리 지점)
│   └── migrate.py               # 마이그레이션 (반복 실행 안전)
├── app/                         # Streamlit 모바일 화면
│   └── components/              #   *_store.py — 두 프론트가 공유하는 데이터 계층
├── web/                         # Streamlit 데스크톱 대시보드
├── infra/systemd/               # 서비스 등록 파일과 install.sh
└── docs/
    ├── project-brief.md
    ├── architecture.md          # 실제 동작 구조
    ├── development-guide.md
    ├── decision-log.md
    └── meetings/
```

데이터 흐름과 역할 경계는 [`docs/architecture.md`](./docs/architecture.md)에
정리되어 있습니다.

## 빠른 시작

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r api/requirements.txt -r gateway/requirements.txt
python3 db/migrate.py
cp gateway/config/config.example.yaml gateway/config/config.yaml

# 라즈베리파이에서 3개 서비스 등록
bash infra/systemd/install.sh
```

프론트만 띄워 화면 작업을 할 때는 백엔드가 없어도 됩니다.
`THERMOSHIFT_API_BASE` 를 설정하지 않으면 store가 자동으로 목데이터로
동작합니다.

```bash
.venv/bin/python -m streamlit run web/main.py
```

## 배포 (Vercel)

`npm run build` 가 `pwa/` 에 stlite 정적 번들 두 개를 만듭니다.

| 경로 | 진입점 | 화면 |
|---|---|---|
| `/` | `app/main.py` | 모바일 |
| `/dashboard/` | `web/main.py` | 데스크톱 대시보드 |

Vercel 프로젝트 환경변수에 `THERMOSHIFT_API_BASE` 를 넣으면 빌드 시점에
번들로 구워집니다. 비어 있으면 목데이터 모드로 뜹니다.

브라우저에서 도는 stlite 는 `requests` 를 쓸 수 없어
`app/components/backend.py` 가 동기 XMLHttpRequest 로 자동 전환합니다.
따라서 API 서버는 **공인 주소로 접근 가능해야 하고**, CORS 허용 출처에
Vercel 도메인이 포함돼야 합니다 (`THERMOSHIFT_ALLOWED_ORIGINS`).

## 협업 흐름

GitHub를 많이 써보지 않은 팀원도 따라올 수 있도록, 처음에는 단순하게 운영합니다.

1. **할 일을 정한다**
   - 가능하면 GitHub Issue로 만들고, 어렵다면 단톡/회의록에 먼저 적어도 됩니다.

2. **작업 전에 최신 상태로 맞춘다**
   - 내 컴퓨터에서 작업한다면 `git pull`을 먼저 합니다.

3. **문서 수정은 가볍게, 코드 수정은 조심해서**
   - 오타, 회의록, 링크 추가는 바로 수정해도 괜찮습니다.
   - 코드 기능 개발이나 큰 변경은 branch 또는 Pull Request를 권장합니다.

4. **작업한 내용을 알아볼 수 있게 저장한다**
   - commit 메시지는 완벽하지 않아도 되지만, “무엇을 했는지”는 보이게 씁니다.
   - 예: `docs: add meeting notes`, `feat: add dashboard draft`

5. **막히면 빨리 공유한다**
   - Git 충돌, 실행 오류, 역할이 애매한 작업은 혼자 오래 붙잡지 말고 팀에 공유합니다.

6. **결정사항은 문서로 남긴다**
   - 회의에서 결정된 내용은 `docs/decision-log.md` 또는 `docs/meetings/`에 남깁니다.
   - 발표/보고서에 재사용할 내용은 Google Drive/Notion에만 두지 말고 필요한 범위에서 repository 문서에도 반영합니다.

자세한 GitHub 사용 규칙은 [`CONTRIBUTING.md`](./CONTRIBUTING.md)에 정리되어 있습니다.

## 관련 문서

- 회의록/운영 문서: Notion, Google Drive에서 관리
- 현장 설치 가이드: Google Docs 문서 참고
- 개발 규칙: [`CONTRIBUTING.md`](./CONTRIBUTING.md)

## 라이선스

아직 미정입니다. 공개 범위와 한이음 제출 조건을 확인한 뒤 결정합니다.
