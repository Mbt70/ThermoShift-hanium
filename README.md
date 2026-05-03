# ThermoShift Hanium

ThermoShift는 중소형 공간의 **쾌적도**와 **전력 사용량**을 함께 고려해 냉난방/환기 운영을 돕는 한이음 프로젝트입니다.

> 목표: 실내 환경 데이터와 사용자 피드백을 바탕으로 쾌적도 저하를 줄이고, 불필요한 에너지 사용을 낮추는 의사결정 보조 시스템을 만든다.

## 문제의식

- 냉난방은 사람마다 체감 쾌적도가 다르고, 공간/시간/인원에 따라 최적 운영이 달라집니다.
- 단순 온도 기준 제어는 불쾌감이나 과도한 전력 사용으로 이어질 수 있습니다.
- 소규모 공간에서도 적용 가능한 가벼운 데이터 기반 운영 도구가 필요합니다.

## 핵심 기능 후보

- 실내 환경 데이터 수집/저장: 온도, 습도, CO₂, 재실 여부 등
- 쾌적도 추정: PMV/PPD 또는 프로젝트 정의 점수 기반
- 전력 사용량/운영비 추정
- 냉난방 운영 추천: 현재 상태, 목표 쾌적도, 전력 절감 조건 반영
- 대시보드: 현재 상태, 히스토리, 추천 액션, 효과 비교

## Repository 구조

```text
.
├── README.md                    # 프로젝트 소개와 빠른 시작
├── CONTRIBUTING.md              # 협업 규칙
├── docs/
│   ├── project-brief.md          # 문제정의/목표/범위
│   ├── architecture.md           # 시스템 구조 초안
│   ├── development-guide.md      # 개발 환경/브랜치/커밋 규칙
│   ├── decision-log.md           # 주요 의사결정 기록
│   └── meetings/                 # 회의록
└── .github/
    ├── PULL_REQUEST_TEMPLATE.md
    └── ISSUE_TEMPLATE/
        ├── bug_report.md
        └── feature_request.md
```

추후 개발이 시작되면 아래처럼 확장합니다.

```text
backend/       # API 서버, DB 연동, 추천 로직
frontend/      # 웹/앱 대시보드
ml/            # 쾌적도 예측, 최적화, 실험 노트
hardware/      # 센서/IoT 연동 코드와 회로/장비 문서
data/          # 샘플 데이터 또는 데이터 스키마 문서
scripts/       # 개발/분석/배포 보조 스크립트
```

## 협업 흐름

1. 작업 단위는 GitHub Issue로 만든다.
2. 브랜치는 `feature/기능명`, `fix/문제명`, `docs/문서명` 형식으로 만든다.
3. 작업 후 Pull Request를 열고 최소 1명 리뷰를 받는다.
4. 회의에서 결정된 내용은 `docs/decision-log.md` 또는 `docs/meetings/`에 남긴다.

## 팀 역할 초안

| 역할 | 담당 |
|---|---|
| PM / 기획 / 일정관리 | Jongmin |
| Frontend | TBD |
| Backend / API | TBD |
| Data / ML / Optimization | TBD |
| Hardware / Sensor | TBD |
| Documentation / Presentation | TBD |

## 바로 할 일

- [ ] 팀원 GitHub collaborator 초대
- [ ] 기술 스택 결정: Frontend / Backend / DB / 센서 연동 방식
- [ ] MVP 범위 확정
- [ ] 첫 회의록 작성
- [ ] 역할 분담과 1주차 작업 Issue 생성

## 라이선스

아직 미정입니다. 공개 범위와 한이음 제출 조건을 확인한 뒤 결정합니다.
