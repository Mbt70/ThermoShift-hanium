# Development Guide

## 초기 세팅

- Runtime: Python 3.13 (`.venv`), Node.js 24 (PWA 빌드용)
- Package manager: pip (`requirements.txt`), npm (`package.json`, PWA 빌드 전용 - 런타임 의존성 없음)
- Backend start command:
  1. DB: `docker compose -f infra/docker-compose.yml up -d` (최초 실행 시 `db/001~003_*.sql`, `seed.sql`이 자동 적용됨)
  2. API: `.venv\Scripts\uvicorn api.main:app --reload --port 8000`
- Frontend start command:
  - 모바일 앱 (로컬 실행): `npm run dev` → `streamlit run app/main.py`
  - 웹 관리자 콘솔: `npm run dev:web` → `streamlit run web/main.py --server.port 8502`
  - 모바일 앱 (PWA 배포): `npm run build` → `pwa/` 산출물을 Vercel이 배포 (`vercel.json` 참고). **PWA 배포 관련 미해결 이슈는 [docs/api-status.md](./api-status.md) 참고.**
- Environment variables: `.env.example` 참고 (DB 접속 정보, API 베이스 URL). 로컬 개발은 기본값만으로도 동작함 - `docker-compose.yml`의 기본 계정과 `api/db.py`/`shared/api_client.py`의 기본값이 서로 맞춰져 있음.

## 추천 개발 순서

1. MVP 기능 목록 확정
2. 화면 와이어프레임 작성
3. 데이터 스키마 정의
4. 더미 데이터 기반 대시보드 구현
5. 쾌적도 계산 로직 연결
6. 전력/추천 로직 추가
7. 센서 또는 외부 데이터 연동

## Definition of Done

작업 완료 기준:

- 기능이 실행된다.
- README 또는 관련 문서가 업데이트됐다.
- PR 설명에 테스트/확인 방법이 있다.
- 다음 작업자가 이어받을 수 있다.
