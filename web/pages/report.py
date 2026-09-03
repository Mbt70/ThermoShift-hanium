import sys
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.room_store import list_rooms
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles
from shared.api_client import api_get

_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>'
)
apply_mobile_styles("report", shared=("dash_shell", "home"))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_id())

selected_id = st.session_state.get("_web_selected_room")
if selected_id and not any(r["id"] == selected_id for r in rooms):
    selected_id = None
if selected_id is None and rooms:
    selected_id = rooms[0]["id"]
    st.session_state["_web_selected_room"] = selected_id

room = next((r for r in rooms if r["id"] == selected_id), None) if selected_id else None

sidebar_col, main_col = st.columns([1, 4], gap="small")

with sidebar_col:
    render_sidebar("report")

with main_col:
    if not rooms or room is None:
        st.switch_page("pages/devices.py")
    else:
        title_col, select_col, spacer_col = st.columns([0.6, 0.8, 4.4], vertical_alignment="center")
        with title_col:
            st.markdown('<h1 class="ts-dash-topbar-title">공간</h1>', unsafe_allow_html=True)
        with select_col:
            names = [r["name"] for r in rooms]
            current_index = next((i for i, r in enumerate(rooms) if r["id"] == room["id"]), 0)
            picked = st.selectbox(
                "공간 선택", names, index=current_index, key="report_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        stats = api_get(f"/ai/rooms/{room['id']}/stats")

        def metric(value, suffix=""):
            return "--" if value is None else f"{value}{suffix}"

        st.markdown(
            f"""
            <div class="ts-report-insight">
              <span class="ts-report-insight-icon">{_CHECK_ICON}</span>
              <p><strong>[MEASURED]</strong> {stats['start']}~{stats['end']} 원본 환경 측정
              {stats['reading_count']}건을 집계했습니다. 전력 절감률은 스마트플러그와 반복 A/B 실험이
              완료될 때까지 표시하지 않습니다.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        kpi_values = [
            ("환경 측정", metric(stats["reading_count"]), "건", "DB 실측 레코드"),
            ("평균 온도", metric(stats["temp_avg"]), "°C", f"범위 {metric(stats['temp_min'])}~{metric(stats['temp_max'])}°C"),
            ("평균 CO₂", metric(stats["co2_avg"]), "ppm", f"최대 {metric(stats['co2_max'])}ppm"),
            ("품질 오류율", metric(stats["invalid_pct"]), "%", "항목별 품질 플래그 기준"),
        ]
        kpi_cols = st.columns(4, gap="small")
        for index, (col, (label, value, unit, note)) in enumerate(zip(kpi_cols, kpi_values)):
            with col:
                with st.container(key=f"ts_dash_kpi_card_measured_{index}", border=True):
                    st.markdown(
                        f"""
                        <div class="ts-dash-kpi-head">
                          <span class="ts-dash-kpi-label">{label}</span>
                        </div>
                        <p class="ts-dash-kpi-value">{value}<span class="ts-dash-kpi-unit">{unit}</span></p>
                        <p class="ts-dash-kpi-sub">{note}</p>
                        """,
                        unsafe_allow_html=True,
                    )

        with st.container(key="ts_dash_report_measured_scope", border=True):
            energy_state = "연동됨" if stats["power_measured"] else "미연동 — 절감률 산출 안 함"
            st.markdown(
                f"""
                <p class="ts-dash-card-title">측정 범위와 검증 상태</p>
                <p>온도 허용범위 이탈 표본: <strong>{metric(stats['temp_out_of_range_pct'], '%')}</strong> ·
                CO₂ 1000ppm 초과 표본: <strong>{metric(stats['co2_high_pct'], '%')}</strong> ·
                재실 추정 표본: <strong>{stats['occupancy_samples']}건</strong> ·
                제어 판단: <strong>{stats['decision_count']}건</strong></p>
                <p>전력계: <strong>{energy_state}</strong> · 명령 전송: {stats['command_sent']}건 ·
                실패/시간초과: {stats['command_failed']}건</p>
                """,
                unsafe_allow_html=True,
            )

        with st.container(key="ts_dash_report_ie_card", border=True):
            st.markdown(
                """
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">
                  <div>
                    <strong style="font-size:15px; color:#0f172a;">📐 산업공학(IE) 최적화 & 제어공학 성과 분석</strong>
                    <span style="font-size:12px; color:#64748b; margin-left:8px;">Multi-Objective Economic MPC & Physics-Guided Estimation</span>
                  </div>
                  <span style="background:#e0f2fe; color:#0369a1; padding:3px 10px; border-radius:6px; font-size:11px; font-weight:600;">
                    검증 프로토콜 준비 단계
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            ie_col1, ie_col2 = st.columns([1, 1], gap="medium")

            with ie_col1:
                st.markdown(
                    """
                    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:12px; font-size:12px; line-height:1.6;">
                      <strong style="font-size:13px; color:#1e293b;">🔬 1. CO₂ 질량보존 + 1차원 Kalman 융합</strong>
                      <p style="color:#64748b; margin:6px 0;">
                        PIR의 빠른 이벤트와 CO₂의 느린 동역학을 결합하는 실공간 확장 모듈입니다. 12 L 목업에서는 사람이 아닌 10 W 히터로 열부하를 재현하므로 기본 비활성화됩니다.
                      </p>
                      <div style="background:#f8fafc; padding:8px 10px; border-radius:6px; font-family:monospace; font-size:11px; color:#334155; margin:6px 0;">
                        V · dC/dt = G_per_person · N_occ - Q_vent · (C - C_out)
                      </div>
                      <table style="width:100%; border-collapse:collapse; margin-top:8px; font-size:11px;">
                        <tr style="border-bottom:1px solid #f1f5f9; color:#64748b;"><th style="text-align:left; padding:4px;">지표</th><th style="text-align:right; padding:4px;">기존 단순 PIR</th><th style="text-align:right; padding:4px; color:#2563eb; font-weight:600;">ThermoShift (물리융합)</th></tr>
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:4px;">빠른 이벤트</td><td style="text-align:right; padding:4px;">PIR 관측</td><td style="text-align:right; padding:4px; color:#2563eb; font-weight:600;">PIR로 즉시 보정</td></tr>
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:4px;">정적 재실</td><td style="text-align:right; padding:4px;">관측 한계</td><td style="text-align:right; padding:4px; color:#2563eb; font-weight:600;">CO₂ 추세로 보완</td></tr>
                        <tr><td style="padding:4px;">검증 상태</td><td style="text-align:right; padding:4px;">—</td><td style="text-align:right; padding:4px; color:#b45309; font-weight:600;">[TARGET] 실제 공간 데이터 필요</td></tr>
                      </table>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with ie_col2:
                st.markdown(
                    """
                    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:12px; font-size:12px; line-height:1.6;">
                      <strong style="font-size:13px; color:#1e293b;">⚡ 2. Occupancy-Aware Economic MPC</strong>
                      <p style="color:#64748b; margin:6px 0;">
                        PMV 기반 쾌적 위반, 전력 비용, 제어 변동을 하나의 목적함수에서 절충합니다. 현재 결과는 교정 전 RC 모델의 시뮬레이션 추정치입니다.
                      </p>
                      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0;">
                        <div style="background:#eff6ff; border-radius:6px; padding:8px; text-align:center;">
                          <div style="color:#1d4ed8; font-size:18px; font-weight:700;">[SIM]</div>
                          <div style="color:#3b82f6; font-size:11px;">동일 RC 모델에서 기준제어와 비교</div>
                        </div>
                        <div style="background:#ecfdf5; border-radius:6px; padding:8px; text-align:center;">
                          <div style="color:#047857; font-size:18px; font-weight:700;">[TARGET]</div>
                          <div style="color:#10b981; font-size:11px;">A/B 반복 실험으로 전력·쾌적 검증</div>
                        </div>
                      </div>
                      <div style="background:#f8fafc; padding:8px 10px; border-radius:6px; font-size:11px; color:#475569; margin-top:6px;">
                        💡 <strong>현재 범위:</strong> 물리 구조가 학습 자유도를 줄이는 장점은 있지만 성능을 보장하지는 않습니다. 새 식별 데이터로 R·C·냉각효율을 교정하고, 전압·전류 실측을 포함한 반복 실험 뒤에만 절감률을 표시합니다.
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
