# ThermoShift 협업 가이드

GitHub를 많이 써보지 않은 팀원도 따라올 수 있도록, 이 프로젝트에서는 최대한 단순하게 협업합니다.

## 제일 중요한 원칙 5개

1. **작업하기 전에 한 줄로 남기기**
   - “제가 대시보드 화면 초안 만들게요”처럼 Issue나 단톡/회의록에 남깁니다.

2. **큰 파일을 바로 덮어쓰지 않기**
   - 특히 다른 사람이 작업 중인 파일은 먼저 말하고 수정합니다.

3. **민감한 정보는 올리지 않기**
   - API key, 비밀번호, 개인정보, 원본 민감 데이터는 GitHub에 올리지 않습니다.

4. **완성도가 낮아도 진행 상황을 공유하기**
   - 완벽하게 끝낸 뒤 공유하기보다, 막히면 빨리 알려주는 게 좋습니다.

5. **결정된 내용은 문서로 남기기**
   - 카톡/Discord에서 결정한 내용도 나중에 찾기 쉽게 README, docs, 회의록 중 하나에 정리합니다.

## GitHub를 처음 쓰는 팀원을 위한 흐름

### 1. 작업할 내용 정하기

예시:

- CO₂ 센서 후보 조사
- 대시보드 화면 구성 초안
- baseline KPI 정리
- 센서 데이터 저장 형식 설계

작업할 내용은 가능하면 GitHub Issue로 만들고, 어렵다면 단톡/회의록에 먼저 적어도 됩니다.

### 2. 내 컴퓨터에서 작업하기

처음 한 번만 repository를 내려받습니다.

```bash
git clone https://github.com/Mbt70/ThermoShift-hanium.git
cd ThermoShift-hanium
```

이미 받은 적이 있다면, 작업 전에 최신 상태로 맞춥니다.

```bash
git pull
```

### 3. 파일 수정하기

문서 작업은 GitHub 웹사이트에서 바로 수정해도 괜찮습니다.

코드 작업은 가능하면 VS Code 같은 에디터에서 수정합니다.

### 4. 변경 내용 저장하기

```bash
git status
git add 파일이름
git commit -m "docs: update sensor candidate list"
git push
```

처음에는 commit 메시지가 완벽하지 않아도 됩니다. 대신 “무엇을 했는지”만 알아볼 수 있게 씁니다.

좋은 예시:

```text
docs: add meeting notes
feat: add dashboard draft
fix: correct sensor data format
```

아쉬운 예시:

```text
update
asdf
final_final
```

## Branch 규칙 — 처음엔 단순하게

초기에는 너무 복잡하게 하지 않습니다.

- 문서만 조금 수정: `main`에 바로 수정해도 괜찮음
- 코드 기능 개발: branch를 만들어서 작업 권장
- 여러 사람이 같은 파일을 만질 것 같음: branch 사용 권장

Branch 이름 예시:

```text
feature/dashboard
feature/sensor-logging
docs/meeting-notes
fix/data-format
```

Branch를 만드는 명령어:

```bash
git checkout -b feature/dashboard
```

## Pull Request는 언제 쓰나요?

Pull Request, PR은 “제가 이렇게 바꿨는데 합쳐도 될까요?”라고 보여주는 공간입니다.

아래 경우에는 PR을 권장합니다.

- 코드 기능을 추가했을 때
- 기존 동작을 바꿨을 때
- 다른 사람 작업에 영향을 줄 수 있을 때
- 발표/보고서에 중요한 문서를 크게 수정했을 때

아래 경우에는 처음엔 바로 수정해도 됩니다.

- 오타 수정
- 회의록 추가
- 참고 링크 추가
- 간단한 문서 보완

## Issue는 어떻게 쓰나요?

Issue는 “해야 할 일 카드”라고 생각하면 됩니다.

좋은 Issue 예시:

```text
제목: CO₂ 센서 후보 3개 비교

해야 할 일:
- 가격 조사
- 측정 범위 확인
- Raspberry Pi/ESP32 연결 가능 여부 확인
- 구매 링크 정리

담당: 최주하
마감: 5/15 전
```

## 파일을 어디에 두나요?

- 회의록: `docs/meetings/`
- 프로젝트 설명/목표: `README.md`, `docs/project-brief.md`
- 시스템 구조: `docs/architecture.md`
- 개발 방법: `docs/development-guide.md`
- 센서/설치 관련 자료: 추후 `hardware/`
- 대시보드/프론트엔드 코드: 추후 `frontend/`
- 서버/DB/API 코드: 추후 `backend/`
- 실험/분석 코드: 추후 `ml/` 또는 `scripts/`

## 충돌이 났을 때

Git에서 conflict가 나면 당황하지 말고 바로 공유합니다.

추천 문장:

> 저 이 파일에서 conflict 났는데, 제가 수정한 부분은 OO입니다. 같이 확인 가능할까요?

혼자 억지로 고치다가 다른 사람 작업을 지우는 것보다, 빨리 말하는 게 훨씬 안전합니다.

## 우리 팀의 현실적인 운영 방식

처음부터 완벽한 GitHub workflow를 목표로 하지 않습니다.

1. 문서와 역할을 GitHub에 모아둔다.
2. 작업은 Issue로 가볍게 관리한다.
3. 코드는 가능하면 branch + PR로 합친다.
4. 막히면 단톡/회의에서 빠르게 공유한다.
5. 발표/보고서에 쓸 결정과 결과는 문서로 남긴다.

이 정도만 지켜도 충분히 협업 기록이 남고, 나중에 보고서/발표/포트폴리오로 재사용하기 좋아집니다.
