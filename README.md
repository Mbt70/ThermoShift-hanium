# ThermoShift — Hanium DreamUp

ThermoShift는 재실자가 만드는 열부하와 실내 열환경의 미래 변화를 추정해,
**쾌적도와 전력 사용을 함께 최적화**하는 소규모 공간용 실시간 제어
프로토타입입니다.

> 센서를 이용해 사람을 단순히 감지하는 데서 끝나지 않고, 재실 열부하를
> 추정하고 미래 온열환경을 예측해 필요한 만큼만 냉난방하는 것이 목표입니다.

## 왜 필요한가

고정 설정온도 제어는 공간이 비어 있어도 동작하거나, 사람이 이미 쾌적한데도
온도 한 점을 맞추기 위해 에너지를 사용할 수 있습니다. 반대로 절전만
우선하면 재실자의 불쾌감이 커집니다. ThermoShift에서 온도는 목표가 아니라
미래 쾌적도를 계산하기 위한 **예측 상태**입니다. 다음 세 항목을 목적함수에서
다룹니다.

- 에너지 비용 또는 전력 사용 대리지표
- 재실 확률로 가중한 PMV 쾌적 허용대역 이탈
- 잦은 액추에이터 제어 변경

## Physics–Estimation–Optimization 통합 구조

```text
온도·습도·CO₂ + PIR·문 센서
              ↓
       재실 상태 추정(HMM)
              ↓
   재실 열부하 추정 / 실험 입력
              ↓
   현장별 RC 열모델 파라미터 식별
              ↓
 Economic MPC 또는 안전 규칙 제어
              ↓
 펠티어·IR 제어 → 상태 확인 → 로그·KPI
```

개별 알고리즘을 새로 발명했다는 주장이 아니라, 제한된 예산의 소규모
공간에서도 동작하도록 이 과정을 하나의 장애 허용형 폐루프 시스템으로
통합한 것이 기술적 차별점입니다.

## 세 가지 기술적 차별점

### 1. Physics-Guided Small-Data Modeling

단일 존 grey-box RC 구조를 먼저 정의합니다.

```text
C·dT/dt = (T_out - T)/R + Q_internal + Q_actuator + w
```

데이터로 거대한 black-box 모델을 학습하는 대신 현장별 열저항 `R`, 유효
열용량 `C`, 액추에이터 효율과 외란 항을 식별합니다. 물리 구조는 필요한
자유도를 줄여 주지만, 적은 데이터만으로 정확도나 안정성이 자동 보장되는
것은 아닙니다.

### 2. Sensor-Fusion State Estimation

PIR은 빠른 움직임 이벤트에 강하고, CO₂ 변화는 장시간 정적 재실 상황을
보완할 수 있습니다. 현재 게이트웨이는 PIR·문·CO₂ 특징을 HMM으로 융합해
`EMPTY / TRANSITION / OCCUPIED` 상태를 추정합니다.

실제 공간용 인원수 추정 프로토타입은 다음 질량보존 관계를 사용합니다.

```text
V·dC/dt = G·N - Q_vent·(C - C_out)
```

환기량, 문·창문 개방, 센서·혼합 지연의 영향을 받으므로 “정적 사각지대
완전 해결”이라고 주장하지 않습니다. 정확한 표현은 **PIR 단독 대비 정적
재실 상황의 관측 가능성 향상**입니다.

### 3. Occupancy-Aware Economic MPC

60분 예측구간에서 이진 제어 후보를 비교합니다.

```text
min Σ [ λe·normalized_energy(k)
      + λc·P_occupied(k)·max(0, |PMV(k)| - 0.5)²
      + λs·|u(k)-u(k-1)| ]
```

PMV 허용대역 이탈은 현재 hard constraint가 아닌 soft penalty입니다. 따라서
“24℃를 항상 맞추는 제어”가 아니라 “재실자가 쾌적한 범위 안에서 불필요한
동작을 줄이는 제어”를 지향합니다. 설정온도 추종 오차는 이 목적함수에
없습니다. 펠티어 입력전력을 계측·교정하기 전 `normalized_energy`는 이진
가동시간 대리지표이고, 교정 후에는 `Power[W] × runtime[h]`로 Wh를 함께
보고합니다. TOU는 아직 실제 요금제 연동이 아닌 피크시간 가중 시나리오입니다.

## 12 L 목업 실증 범위

- 크기: `20 cm × 20 cm × 30 cm = 0.012 m³ (12 L)`
- 냉각 출력: 펠티어 기반 냉각 장치
- 합성 열부하: 최대 10 W 히팅패드, duty 제어
- 센서: 온도·습도·CO₂·PIR·문 상태
- 제어·수집: ESP32 → MQTT → Raspberry Pi gateway → PostgreSQL/API

목업의 히터는 사람의 **열**만 재현하며 사람의 CO₂ 발생과 PIR 신호를
동시에 재현하지 않습니다. 따라서 히터 duty로 환산한 값은 실제 인원수가
아니라 스케일링 계약상의 “합성 재실자 상당 열부하”입니다.

목업과 실제 공간은 열용량, 표면적/부피비, 자연대류와 혼합 특성이 다릅니다.
목업의 파라미터와 절감률을 45m³ 공간에 1:1 이전하지 않습니다. 실제 공간
확장 시 같은 모델 구조와 제어 코드는 재사용하되 `R`, `C`, 환기량, 내부발열,
액추에이터 효율을 현장 데이터로 다시 식별합니다.

## 데이터와 성과 표기 원칙

현재까지 모은 데이터는 개발·통신·분석 파이프라인 점검용이며, 공식 성능
검증에 적합한 통제 실험 데이터가 아닙니다. 현재 저장된 수치로 에너지
절감률, 재실 정확도 또는 쾌적도 개선을 주장하지 않습니다.

- `[MEASURED]`: 사전에 정한 프로토콜로 목업에서 실제 측정한 결과
- `[SIM]`: 명시된 가정과 동일 모델 내 비교로 얻은 시뮬레이션 결과
- `[TARGET]`: 향후 실증 목표

전력계 연결 전 MPC 출력은 `[SIM]` 가동시간 비교이며 실제 kWh 절감률이
아닙니다. 실험 설계와 주장 가능 범위는
[`docs/submission-guide.md`](docs/submission-guide.md)를 따릅니다.

## 안전·신뢰성 설계

- 센서 stale 시 현 상태 유지
- 수동 조작 후 자동제어 잠금
- 최소 가동·정지 시간과 명령 rate limit
- 히터 45℃ 상한 및 120초 명령 watchdog
- PostgreSQL 연결 장애 시 Raspberry Pi SQLite 버퍼에 저장 후 재전송
- 제어 판단, 실행 여부, 차단 원인을 분리 기록
- 서명된 API 세션과 공간 소유권 검사

## 실행과 검증

```bash
cp .env.example .env
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 저장소 루트에서 전체 게이트웨이 단위 테스트
.venv/bin/python -m pytest -q

# PWA 정적 빌드
npm run build
```

펌웨어는 `firmware/secrets.example.h`를 `firmware/secrets.h`로 복사하고
로컬 Wi-Fi 값을 설정해야 컴파일됩니다. 실제 비밀정보는 커밋하지 않습니다.

## Repository

```text
api/       FastAPI, PostgreSQL API, 인증·AI 해설
app/       stlite 기반 모바일 PWA
web/       운영자 대시보드
gateway/   MQTT 수집, 상태추정, 안전 정책, 제어, 오프라인 버퍼
firmware/  ESP32 센서·펠티어·히터·IR 노드
ml/        RC 식별, HMM, PMV, MPC, 분석 실험
db/        PostgreSQL 스키마와 마이그레이션
infra/     Docker, EC2, systemd, MQTT 구성
docs/      아키텍처·배포·공모전 주장 및 실험 가이드
```

## 참고 기준

- [ISO 7730:2025 — PMV/PPD 기반 열쾌적 평가](https://www.iso.org/standard/85803.html)
- [ASHRAE Handbook, Thermal Comfort — 휴식 성인 약 100 W 대표값](https://handbook.ashrae.org/Handbooks/F21/SI/F21_Ch09/F21_Ch09_si.aspx)
- [Yang et al. (2018) — PMV와 에너지 다목적 MPC](https://doi.org/10.1016/j.enbuild.2018.03.082)
- [Chen et al. (2015) — 사용자 피드백 기반 쾌적·에너지 MPC](https://doi.org/10.1016/j.enbuild.2015.06.002)

PMV는 환경과 의복·활동량 가정에 따른 모델 평가값입니다. 사람이 들어갈 수
없는 목업에서 계산한 PMV를 실제 재실자의 만족도 실증값으로 표현하지 않습니다.

## 라이선스

공개 및 한이음 제출 조건 확인 후 확정합니다.
