# ThermoShift API 컨테이너 (EC2 배포용)
#
# API의 코파일럿 MPC 시뮬레이션이 ml/의 순수 계산 모듈을 사용한다. 전체
# ml/에는 대형 실험 CSV가 있으므로 런타임에 필요한 네 파일만 복사한다.
#
# 로컬 개발 venv(.venv/pyvenv.cfg)와 동일한 Python 3.13 을 쓴다.
# requirements.txt 가 고정한 버전들(numpy/pandas/pyarrow 등)이 그 venv
# 기준으로 설치된 것이라 3.13 wheel 은 이미 존재가 확인된 상태다.
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
# psycopg-binary 가 libpq 를 wheel 안에 번들하므로 libpq-dev 등 별도 시스템
# 패키지 설치가 필요 없다 (requirements.txt 에 psycopg==3.3.4 와
# psycopg-binary==3.3.4 가 함께 고정되어 있어 바이너리 구현이 쓰인다).
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY ml/__init__.py ml/comfort_model.py ml/mpc_controller.py ml/thermal_model.py ./ml/

EXPOSE 8000

# systemd 유닛(infra/systemd/thermoshift-api.service)의 ExecStart 와 동일한
# 진입점: api/main.py 의 app 객체.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
