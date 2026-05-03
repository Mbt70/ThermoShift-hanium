# Architecture Draft

## 전체 구조 초안

```text
Sensor / Input Data
        ↓
Backend API / Data Processing
        ↓
Comfort & Energy Logic
        ↓
Dashboard / Recommendation UI
```

## 주요 모듈

### 1. Data Input

- 온도
- 습도
- CO₂
- 재실 여부
- 외부 날씨
- 전력 사용량 또는 추정 변수

### 2. Comfort Model

초기에는 단순 규칙 기반으로 시작하고, 데이터가 쌓이면 모델을 고도화합니다.

- Rule-based comfort score
- PMV/PPD 참고
- 사용자 피드백 기반 보정

### 3. Energy Logic

- 냉난방 설정 변화에 따른 전력 영향 추정
- 시간대별 사용 패턴 분석
- 절감 가능 구간 탐지

### 4. Recommendation

예시:

- “현재 쾌적도는 양호하므로 설정온도를 1℃ 완화해도 됩니다.”
- “CO₂ 농도가 높아 환기가 필요합니다.”
- “습도가 높아 체감온도가 상승할 수 있습니다.”

## 기술 스택 후보

아직 결정 전입니다.

- Frontend: React / Next.js / Streamlit 중 선택
- Backend: FastAPI / Node.js 중 선택
- DB: SQLite / PostgreSQL / Supabase 중 선택
- Data/ML: Python, pandas, scikit-learn
- Deployment: Vercel / Render / Railway / GitHub Pages 중 선택
