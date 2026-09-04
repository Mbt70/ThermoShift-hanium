# ThermoShift 20분 파일럿 데이터 — Run 0001

2026-09-03에 20×20×30 cm(약 12 L) 목업에서 수집한 센서·제어 로그다.
GitHub에서 개별 CSV를 보거나 `thermoshift_run_0001_csv.zip`을 내려받을 수
있다. 모든 시각은 UTC ISO 8601이며 한국 표준시는 UTC+9다.

## 용도와 품질 범위

이 데이터의 품질 표시는 `PILOT_PIPELINE_ONLY_NOT_TRAINING_QUALITY`다.
센서→MQTT→DB→CSV 시간축과 문 개방 이벤트가 기록되는지 확인하는 파일럿이며,
RC/PINN 파라미터 식별이나 에너지 절감률 산출에 사용하지 않는다.

- 환경 센서 240행(약 5초 간격), 온도 변화폭 0.19°C
- PIR·문 센서 각각 1,186행(약 1초 간격)
- 문 개방은 센서 기준 약 112초
- 펠티어 ON/OFF는 명령 시각이며 전기적 상태 ACK가 아니다
- 히터의 실제 OFF 시각이 확인되지 않아 히터 ON 이후 구간은 교란 가능
- 전력계가 연결되지 않아 `power_readings.csv`는 비어 있음
- 외기/목업 외부 온도를 별도로 측정하지 않음

정확한 이벤트 시각과 제한사항은 `manifest.json`, 구간 요약은
`phase_summary.csv`를 우선 확인한다. `raw_payload`는 센서가 보낸 원문을
재현성 확인용으로 보존한 것이다.

## 파일

| 파일 | 내용 |
|---|---|
| `sensor_env.csv` | 온도·습도·CO₂ |
| `sensor_pir.csv` | PIR 움직임 |
| `sensor_door.csv` | 문 열림/닫힘 |
| `heater_log.csv` | 게이트웨이 히터 지령 기록(물리 ACK 아님) |
| `control_decisions.csv` | 제어 판단과 근거 |
| `occupancy_estimates.csv` | 재실 상태·확률 추정 |
| `power_readings.csv` | 전력 측정(이번 run은 0행) |
| `phase_summary.csv` | 실제 이벤트 경계별 센서 변화 |
| `model_timeline_30s.csv` | 30초 정렬 학습 후보표(이번 run은 전 행 부적합) |
| `training_quality.json` | 자동 학습 품질 판정과 거절 사유 |
| `manifest.json` | 실험 메타데이터·품질 범위·제한사항 |

## 재현

운영 DB에 같은 run이 남아 있다면 저장소 루트에서 다음 명령으로 다시 만든다.

```bash
python -m ml.export_experiment 1
python -m ml.prepare_experiment .data/experiments/run_0001
```

품질 게이트를 통과하지 않은 결과는 `ml/params/thermal.json` 등 운영 파라미터로
승격하지 않는다.
