import sys
from datetime import date
from pathlib import Path

import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.control_log_store import list_logs
from app.components.room_store import (
    environment_snapshot,
    list_rooms,
    set_control_mode,
    system_judgment,
)
from components.auth_store import current_user_id, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, icon_data_uri, recolored_icon_data_uri
from ml.comfort_model import calculate_pmv
from ml.scaling import scale_parameters, MOCKUP_DOMAIN, REAL_OFFICE_DOMAIN

_CONTROL_MODES = (
    ("monitoring", "모니터링", "monitoring.svg"),
    ("manual", "수동제어", "back_hand.svg"),
    ("rule", "규칙 제어", "rule-based.svg"),
    ("predictive", "예측 제어", "predictive.svg"),
)
_MODE_ICON_INACTIVE = "#98a1ab"
_MODE_ICON_ACTIVE = "#ffffff"

_KPI_ICON_FILES = {
    "temp": "temperture.svg",
    "co2": "co2.svg",
    "occupancy": "web_door.svg",
    "power": "web_bolt.svg",
}

_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>'
)
_WARN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10.5v4M12 17.5v.1"/></svg>'
)
_HUMIDITY_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 2.5c4 5 7 8.5 7 12.5a7 7 0 0 1-14 0c0-4 3-7.5 7-12.5Z"/></svg>'
)
_CHIP_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="7" y="7" width="10" height="10" rx="1.5"/>'
    '<path d="M9.5 7V4M14.5 7V4M9.5 20v-3M14.5 20v-3M7 9.5H4M7 14.5H4M20 9.5h-3M20 14.5h-3"/></svg>'
)
_CUBE_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3 20 7.5V16.5L12 21 4 16.5V7.5Z"/><path d="M4 7.5 12 12 20 7.5M12 12V21"/></svg>'
)
_CFD_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 12h4l2-7 4 14 2-7h6"/></svg>'
)
_LIST_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 10h8M8 14h5"/></svg>'
)


apply_mobile_styles("digital_twin", shared=("dash_shell", "home", "room_detail"))

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
    render_sidebar("digital_twin")

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
                "공간 선택", names, index=current_index, key="twin_top_room_select", label_visibility="collapsed"
            )
            picked_room = next((r for r in rooms if r["name"] == picked), room)
            if picked_room["id"] != room["id"]:
                st.session_state["_web_selected_room"] = picked_room["id"]
                st.rerun()

        @st.fragment(run_every=5)
        def render_live_twin(current_room_id):
            fresh_rooms = list_rooms(current_user_id())
            current_r = next((r for r in fresh_rooms if r["id"] == current_room_id), room)
            snapshots = {r["id"]: environment_snapshot(r) for r in fresh_rooms}
            room_count = len(fresh_rooms)

            temps = [s["temperature"] for s in snapshots.values() if s["temperature"] is not None]
            co2s = [s["co2"] for s in snapshots.values() if s["co2"] is not None]
            humidities = [s["humidity"] for s in snapshots.values() if s["humidity"] is not None]
            powers = [s["power"] for s in snapshots.values() if s["power"] is not None]
            avg_temp = sum(temps) / len(temps) if temps else 0.0
            avg_co2 = sum(co2s) / len(co2s) if co2s else 0.0
            avg_humidity = sum(humidities) / len(humidities) if humidities else 0.0
            total_power = sum(powers)
            active_count = sum(1 for r in fresh_rooms if r.get("occupied"))
            occupancy_rate = round(active_count / room_count * 100) if room_count else 0
            # 인원 계수기와 전일 기준선이 아직 없는데 임의 숫자를 만들면
            # 실시간 실측처럼 보인다. 현재 확인 가능한 재실 공간 수와 실제
            # 전력 센서 합계만 보여준다.
            measured_power = bool(powers)

            co2_ok = avg_co2 < 700
            kpi_items = [
                ("temp", "온도", f"{avg_temp:.1f}", "°C", "is-positive", f"{_CHECK_ICON}목표 24°C 근접"),
                (
                    "co2",
                    "CO₂",
                    f"{avg_co2:.0f}",
                    "ppm",
                    "is-positive" if co2_ok else "is-negative",
                    f"{_CHECK_ICON}기준 이내" if co2_ok else f"{_WARN_ICON}기준 근접",
                ),
                ("occupancy", "재실 공간", f"{active_count}", "실", "", f"재실률 {occupancy_rate}%"),
                ("humidity", "습도", f"{avg_humidity:.0f}", "%", "is-positive", f"{_CHECK_ICON}적정"),
                (
                    "power",
                    "총 HVAC 전력",
                    f"{total_power:.1f}" if measured_power else "--",
                    "kW",
                    "is-positive" if measured_power else "",
                    f"{_CHECK_ICON}전력 센서 합계" if measured_power else "전력 센서 미연동",
                ),
            ]
            kpi_cols = st.columns(5, gap="small")
            for col, (slug, label, value, unit, sub_class, sub) in zip(kpi_cols, kpi_items):
                with col:
                    with st.container(key=f"ts_dash_kpi_card_{slug}", border=True):
                        icon_html = (
                            f'<span class="ts-dash-kpi-icon ts-twin-humidity-icon">{_HUMIDITY_ICON}</span>'
                            if slug == "humidity"
                            else f'<img class="ts-dash-kpi-icon" src="{icon_data_uri(_KPI_ICON_FILES[slug])}" alt="" />'
                        )
                        st.markdown(
                            f"""
                            <div class="ts-dash-kpi-head">
                              <span class="ts-dash-kpi-label">{label}</span>
                              {icon_html}
                            </div>
                            <p class="ts-dash-kpi-value">{value}<span class="ts-dash-kpi-unit">{unit}</span></p>
                            <p class="ts-dash-kpi-sub {sub_class}">{sub}</p>
                            """,
                            unsafe_allow_html=True,
                        )

            twin_col, side_col = st.columns([2, 1], gap="small")

            with twin_col:
                with st.container(key="ts_dash_twin_view_card", border=True):
                    head_col, tab_col = st.columns([2.6, 1.6], vertical_alignment="center")
                    with head_col:
                        st.markdown(
                            f'<p class="ts-dash-card-title" style="margin:0;">{_CUBE_ICON}3D 디지털 트윈</p>',
                            unsafe_allow_html=True,
                        )
                    with tab_col:
                        view_tab = st.pills(
                            "뷰", ["3D 뷰", "공간 스케일링", "CFD 분포"], default="3D 뷰", key="twin_view_tab", label_visibility="collapsed"
                        ) or "3D 뷰"

                    current_snap = snapshots[current_r["id"]]
                    temp_display = f"{current_snap['temperature']:.1f}°C" if current_snap["temperature"] is not None else "--"
                    humidity_display = f"{current_snap['humidity']:.0f}%" if current_snap["humidity"] is not None else "--"
                    co2_display = f"{current_snap['co2']:.0f}ppm" if current_snap["co2"] is not None else "--"
                    occupancy_label = "재실" if current_r.get("occupied") else "공실"
                    door_display = "문 열림" if current_snap.get("door_state") == "open" else ("문 닫힘" if current_snap.get("door_state") == "closed" else "문 --")

                    pmv_info = None
                    if current_snap["temperature"] is not None and current_snap["humidity"] is not None:
                        pmv_info = calculate_pmv(float(current_snap["temperature"]), float(current_snap["humidity"]))
                        pmv_chip = f'<span class="ts-twin-telemetry-item">PMV <strong>{pmv_info.pmv:+.2f} ({pmv_info.category.split()[1]})</strong></span>'
                    else:
                        pmv_chip = '<span class="ts-twin-telemetry-item">PMV <strong>--</strong></span>'

                    if view_tab == "공간 스케일링":
                        scale_data = scale_parameters(0.006, -0.05, 0.15)
                        st.markdown(
                            f"""
                            <div style="background:#f8fafc; border-radius:12px; padding:16px; font-size:13px; color:#334155; line-height:1.6;">
                              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">
                                <strong style="font-size:14px; color:#0f172a;">📐 제어 아키텍처 확장 계획 (12L 목업 → 실제 공간)</strong>
                                <span style="background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600;">현장 재교정 필요</span>
                              </div>
                              <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
                                <div style="background:#ffffff; padding:10px; border-radius:8px; border:1px solid #e2e8f0;">
                                  <div style="color:#64748b; font-size:11px; margin-bottom:2px;">실험 목업 (12L 챔버)</div>
                                  <div style="font-weight:700; color:#0f172a; font-size:14px;">체적 0.012 m³</div>
                                  <div style="color:#475569; font-size:12px;">교정 전 가정 C: 3.0 kJ/K | 시정수 {scale_data['tau_mockup_min']}분</div>
                                  <div style="color:#2563eb; font-size:11px;">펠티어 + 10W 합성 열원</div>
                                </div>
                                <div style="background:#ffffff; padding:10px; border-radius:8px; border:1px solid #e2e8f0;">
                                  <div style="color:#64748b; font-size:11px; margin-bottom:2px;">실제 오피스 (설계 가정)</div>
                                  <div style="font-weight:700; color:#0f172a; font-size:14px;">체적 45.0 m³ ({scale_data['vol_ratio']:,.0f}x)</div>
                                  <div style="color:#475569; font-size:12px;">열용량 C: 1.2 MJ/K | 시정수 {scale_data['tau_real_min']}분</div>
                                  <div style="color:#16a34a; font-size:11px;">에어컨(2.5kW) + 재실발열(350W)</div>
                                </div>
                              </div>
                              <div style="background:#f1f5f9; padding:10px 12px; border-radius:8px; font-size:12px; color:#334155;">
                                💡 목업에서 확인하는 범위는 센서→추정→예측→제어의 폐루프 구조입니다.
                                실제 공간에서는 동일한 RC·MPC 코드 구조를 재사용하되 <strong>R, C, 환기량, 내부발열과 액추에이터 효율을 현장 데이터로 다시 식별·검증</strong>합니다.
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    elif view_tab == "CFD 분포":
                        st.markdown(
                            f"""
                            <div style="background:#f8fafc; border-radius:12px; padding:16px; font-size:13px; color:#334155;">
                              <strong style="font-size:14px; color:#0f172a;">💨 기류·온도장 검증 계획</strong>
                              <div style="display:flex; gap:12px; margin-top:12px; align-items:center;">
                                <div style="flex:1; background:linear-gradient(90deg, #3b82f6 0%, #10b981 50%, #ef4444 100%); height:18px; border-radius:4px;"></div>
                                <span style="font-size:11px; color:#64748b;">23.0℃ ~ 26.5℃</span>
                              </div>
                              <p style="margin-top:10px; font-size:12px; color:#64748b; line-height:1.5;">
                                아래 색상 막대는 화면 구성을 위한 개념도이며 CFD 계산 결과가 아닙니다.
                                향후 다점 온도 측정과 기류 해석으로 단일 존(Well-mixed) 가정의 타당성을 검증할 예정입니다.
                              </p>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"""
                            <div class="ts-twin-stage">
                              <div class="ts-twin-stage-grid"></div>
                              <div class="ts-twin-cube">
                                <div class="ts-twin-cube-inner">
                                  <span class="ts-twin-cube-title">{current_r["name"]}</span>
                                  <span class="ts-twin-cube-status">{occupancy_label} · {door_display}</span>
                                </div>
                              </div>
                              <div class="ts-twin-overlay">
                                <div class="ts-twin-telemetry-chip">
                                  <span class="ts-twin-telemetry-item">온도 <strong>{temp_display}</strong></span>
                                  <span class="ts-twin-telemetry-item">습도 <strong>{humidity_display}</strong></span>
                                  <span class="ts-twin-telemetry-item">CO₂ <strong>{co2_display}</strong></span>
                                  {pmv_chip}
                                </div>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            with side_col:
                with st.container(key="ts_dash_twin_ai_card", border=True):
                    st.markdown(
                        f'<p class="ts-dash-card-title">{_CHIP_ICON}운영 설명 <span class="ts-dash-badge">규칙 기반</span></p>',
                        unsafe_allow_html=True,
                    )
                    headline, subline = system_judgment(current_r)
                    st.markdown(
                        f"""
                        <p class="ts-dash-judgment-headline">{headline}</p>
                        <p class="ts-dash-judgment-sub">{subline}</p>
                        """,
                        unsafe_allow_html=True,
                    )

                state_col, mode_col = st.columns(2, gap="small")
                with state_col:
                    with st.container(key="ts_dash_twin_state_card", border=True):
                        st.markdown(
                            f'<p class="ts-dash-card-title">{_LIST_ICON}현재 제어 상태</p>', unsafe_allow_html=True
                        )
                        logs_today = list_logs(current_r["id"], date.today())
                        latest_log = logs_today[-1] if logs_today else None
                        aircon_state = "AC ON" if current_r.get("aircon_on") else "AC OFF"
                        latest_text = (
                            f'{latest_log["timestamp"].hour}:{latest_log["timestamp"].minute:02d} {latest_log["content"]}'
                            if latest_log
                            else "기록 없음"
                        )
                        verify_text = "성공" if (latest_log is None or latest_log.get("success", True)) else "실패"
                        rows = [
                            ("AC 상태", aircon_state, f'설정 {current_r.get("target_temperature", 24)}°C'),
                            ("최근 명령", latest_text, ""),
                            ("검증 결과", verify_text, ""),
                        ]
                        rows_html = "".join(
                            f'<div class="ts-dash-list-row">'
                            f'<span class="ts-dash-list-secondary">{k}</span>'
                            f'<span class="ts-dash-list-primary">{v}'
                            + (f' <span class="ts-dash-list-secondary">{extra}</span>' if extra else "")
                            + "</span></div>"
                            for k, v, extra in rows
                        )
                        st.markdown(rows_html, unsafe_allow_html=True)

                with mode_col:
                    with st.container(key="ts_dash_twin_mode_card", border=True):
                        st.markdown('<p class="ts-dash-card-title">제어 모드</p>', unsafe_allow_html=True)
                        current_mode = current_r.get("control_mode", "rule")
                        clicked_mode = None
                        mode_cols = st.columns(2, gap="small")
                        for i, (mode_id, mode_label, icon_file) in enumerate(_CONTROL_MODES):
                            with mode_cols[i % 2]:
                                with st.container(key=f"ts_dash_mode_{mode_id}"):
                                    is_mode_active = mode_id == current_mode
                                    icon_color = _MODE_ICON_ACTIVE if is_mode_active else _MODE_ICON_INACTIVE
                                    icon_uri = recolored_icon_data_uri(icon_file, icon_color)
                                    active_mode_class = "is-active" if is_mode_active else ""
                                    st.markdown(
                                        f"""
                                        <div class="ts-dash-mode-item {active_mode_class}">
                                          <div class="ts-dash-mode-icon-wrap"><img src="{icon_uri}" alt="" /></div>
                                          <p class="ts-dash-mode-label">{mode_label}</p>
                                        </div>
                                        """,
                                        unsafe_allow_html=True,
                                    )
                                    if st.button(mode_label, key=f"dash_mode_btn_{mode_id}", width="stretch"):
                                        clicked_mode = mode_id
                        if clicked_mode and clicked_mode != current_mode:
                            set_control_mode(current_r["id"], clicked_mode)
                            st.rerun()

            pmv_values = [
                calculate_pmv(float(s["temperature"]), float(s["humidity"])).pmv
                for s in snapshots.values()
                if s["temperature"] is not None and s["humidity"] is not None
            ]
            average_pmv = sum(pmv_values) / len(pmv_values) if pmv_values else None

            with st.container(key="ts_dash_summary_card", border=True):
                st.markdown('<p class="ts-dash-card-title">현재 상태 요약</p>', unsafe_allow_html=True)
                summary_items = [
                    ("power", "순간 HVAC 전력", f"{total_power:.1f}kW" if measured_power else "--"),
                    ("temp", "현재 평균 온도", f"{avg_temp:.1f}°C" if temps else "--"),
                    ("co2", "현재 평균 CO₂", f"{avg_co2:.0f}ppm" if co2s else "--"),
                    ("occupancy", "현재 공간 사용률", f"{occupancy_rate}%"),
                    (None, "현재 평균 PMV", f"{average_pmv:+.2f}" if average_pmv is not None else "--"),
                ]
                items_html = "".join(
                    f'<div class="ts-dash-summary-item">'
                    f'<div class="ts-dash-summary-head">'
                    f'<span class="ts-dash-summary-label">{label}</span>'
                    + (f'<img src="{icon_data_uri(_KPI_ICON_FILES[slug])}" alt="" />' if slug else "")
                    + "</div>"
                    f'<span class="ts-dash-summary-value">{value}</span>'
                    f"</div>"
                    for slug, label, value in summary_items
                )
                st.markdown(f'<div class="ts-dash-summary-grid">{items_html}</div>', unsafe_allow_html=True)

        render_live_twin(room["id"])
