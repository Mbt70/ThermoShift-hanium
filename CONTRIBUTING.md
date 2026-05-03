# Contributing Guide

ThermoShift 팀 협업 규칙입니다. 너무 무겁게 운영하지 않되, 나중에 발표/보고서/포트폴리오로 재사용할 수 있게 기록을 남깁니다.

## 기본 원칙

- 작업 시작 전 Issue를 만든다.
- 코드/문서 변경은 Pull Request로 합친다.
- 결정사항은 Discord/카톡에만 남기지 말고 문서화한다.
- API key, 비밀번호, 개인정보, 원본 민감 데이터는 repository에 올리지 않는다.

## Branch 규칙

- `main`: 안정 버전. 직접 push 금지 권장.
- `feature/<short-name>`: 새 기능
- `fix/<short-name>`: 버그 수정
- `docs/<short-name>`: 문서 작업
- `experiment/<short-name>`: 실험/프로토타입

예시:

```bash
git checkout -b feature/dashboard-layout
```

## Commit 메시지 규칙

가능하면 아래 prefix를 씁니다.

- `feat:` 기능 추가
- `fix:` 버그 수정
- `docs:` 문서 수정
- `refactor:` 구조 개선
- `test:` 테스트 추가/수정
- `chore:` 설정/잡무

예시:

```text
feat: add comfort score calculation draft
```

## Pull Request 체크리스트

- [ ] 어떤 문제/기능을 다루는지 설명했다.
- [ ] 실행/검증 방법을 적었다.
- [ ] 관련 Issue를 연결했다.
- [ ] 민감정보가 포함되지 않았는지 확인했다.
- [ ] 필요한 문서를 업데이트했다.

## Issue 작성 규칙

좋은 Issue는 아래를 포함합니다.

- 배경: 왜 필요한가?
- 목표: 완료되면 무엇이 되는가?
- 산출물: 코드/문서/화면/실험 결과 중 무엇인가?
- 담당자/마감: 가능하면 명시
