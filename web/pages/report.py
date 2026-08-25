import random
import sys
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components import ai_store
from app.components.room_store import comfort_index, list_rooms
from components.auth_store import current_user_email, is_logged_in
from components.dash_shell import render_sidebar
from components.mobile_ui import apply_mobile_styles, icon_data_uri

_CHECK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7"/></svg>'
)
_WARN_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 10.5v4M12 17.5v.1"/></svg>'
)
_ARROW_UP_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M6 16 18 4M18 4H9M18 4v9"/></svg>'
)
_SIGNAL_ICON = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 15v5M9 11v9M14 7v13M19 3v17"/></svg>'
)
_CHART_ICON = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 17.5 9 11l4 4 8-9"/></svg>'
)

# baseline(자동제어 미적용 구간) 데이터가 쌓이기 전에는 '감소율' 을 계산할 수
# 없다. 실측만으로 말할 수 있는 지표를 쓰고, baseline 이 확보되면 감소율로
# 바꾼다. (docs/architecture.md '아직 남은 것' 참고)
_KPI_ROWS = (
    ("temp", "온도 범위 이탈 시간", "temperture.svg", 20),
    ("co2", "CO₂ 1000ppm 초과 시간", "co2.svg", 10),
    ("ir", "제어 명령 성공률", None, 95),
    ("power", "전력 절감", "web_bolt.svg", 5),
)

# 값이 낮을수록 좋은 지표
_LOWER_IS_BETTER = {"temp", "co2"}


def _trend_chart(days: list[str], scores: list[float], target: float) -> alt.LayerChart:
    df = pd.DataFrame({"day": days, "값": scores, "구분": "쾌적도 지수"})
    target_df = pd.DataFrame({"day": days, "값": [target] * len(days), "구분": "목표 80점"})
    color_scale = alt.Scale(domain=["쾌적도 지수", "목표 80점"], range=["#4a8f6d", "#c65b4e"])

    line = (
        alt.Chart(df)
        .mark_line(strokeWidth=2.4)
        .encode(
            x=alt.X("day:O", title=None, axis=alt.Axis(grid=False, labels=False, ticks=False)),
            y=alt.Y("값:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("구분:N", scale=color_scale, legend=alt.Legend(title=None, orient="bottom")),
        )
    )
    target_line = (
        alt.Chart(target_df)
        .mark_line(strokeWidth=1.6, strokeDash=[5, 4])
        .encode(
            x=alt.X("day:O"),
            y=alt.Y("값:Q"),
            color=alt.Color("구분:N", scale=color_scale, legend=alt.Legend(title=None, orient="bottom")),
        )
    )
    return (
        alt.layer(line, target_line)
        .properties(height=150)
        .configure_axis(labelFont="Inter", titleFont="Inter", grid=True, gridColor="#eef2f4", labelFontSize=9)
        .configure_view(strokeWidth=0)
        .configure_legend(labelFont="Inter", symbolType="stroke", labelFontSize=10, padding=2)
    )


apply_mobile_styles("report", shared=("dash_shell", "home"))

if not is_logged_in():
    st.switch_page("pages/login.py")

rooms = list_rooms(current_user_email())

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

        end_date = date.today()
        start_date = end_date - timedelta(days=6)
        week_seed = f"report-{room['id']}-{end_date.isocalendar()[1]}"

        # 백엔드가 있으면 실측 집계와 AI 요약을 가져온다.
        # 없으면(팀원 로컬 개발) 아래에서 기존 목데이터로 화면을 채운다.
        report = ai_store.report(room["id"], start_date, end_date)
        real = report.get("stats") if report else None
        ai_summary = report.get("ai") if report else None

        if real:
            kpi_values = {
                "temp": real.get("temp_out_of_range_pct"),
                "co2": real.get("co2_high_pct"),
                "ir": real.get("command_success_pct"),
                # 스마트 플러그가 없어 전력은 측정 자체가 되지 않는다. 지어내지 않는다.
                "power": None,
            }
            comfort_score = comfort_index(room)
        else:
            kpi_values = {
                "temp": round(random.Random(f"{week_seed}-temp").uniform(8, 28)),
                "co2": round(random.Random(f"{week_seed}-co2").uniform(2, 14)),
                "ir": round(random.Random(f"{week_seed}-ir").uniform(90, 99)),
                "power": round(random.Random(f"{week_seed}-power").uniform(12, 22), 1),
            }
            comfort_score = comfort_index(room)

        def _kpi_ok(slug: str, value, goal: float):
            """달성 여부. 측정값이 없으면 None(판정 불가)."""
            if value is None:
                return None
            return value <= goal if slug in _LOWER_IS_BETTER else value >= goal

        kpi_ok = {slug: _kpi_ok(slug, kpi_values[slug], goal) for slug, _, _, goal in _KPI_ROWS}
        kpi_goal_text = {
            "temp": "목표 20% 이하",
            "co2": "목표 10% 이하",
            "ir": "목표 95% 이상",
            "power": "목표 5% 이상",
        }
        kpi_sub = {}
        for slug, _, _, _goal in _KPI_ROWS:
            if kpi_ok[slug] is None:
                kpi_sub[slug] = "전력 실측 장비 미설치"
            else:
                kpi_sub[slug] = f"{kpi_goal_text[slug]} {'달성' if kpi_ok[slug] else '미달'}"

        def _kpi_display(slug: str) -> str:
            value = kpi_values[slug]
            if value is None:
                return '<span class="ts-report-nodata">측정 없음</span>'
            return f'{value:g}<span class="ts-dash-kpi-unit">%</span>'

        # --- 요약 배너 ---
        if ai_summary:
            st.markdown(
                f"""
                <div class="ts-report-insight">
                  <span class="ts-report-insight-icon">{_CHECK_ICON}</span>
                  <p>{ai_summary["summary"]}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif real:
            measured = (
                f"{start_date:%m/%d}~{end_date:%m/%d} 측정 {real.get('reading_count', 0)}건 · "
                f"평균 {real.get('temp_avg')}°C · CO₂ 평균 {real.get('co2_avg')}ppm · "
                f"제어 판단 {real.get('decision_count', 0)}회 중 실제 전송 {real.get('executed_count', 0)}회"
            )
            st.markdown(
                f"""
                <div class="ts-report-insight">
                  <span class="ts-report-insight-icon">{_CHART_ICON}</span>
                  <p>{measured}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="ts-report-insight">
                  <span class="ts-report-insight-icon">{_WARN_ICON}</span>
                  <p>백엔드에 연결되지 않아 예시 데이터를 표시하고 있습니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        kpi_cols = st.columns(4, gap="small")
        for col, (slug, label, icon_file, _goal) in zip(kpi_cols, _KPI_ROWS):
            with col:
                with st.container(key=f"ts_dash_kpi_card_{slug}", border=True):
                    icon_html = (
                        f'<span class="ts-dash-kpi-icon ts-report-signal-icon">{_SIGNAL_ICON}</span>'
                        if icon_file is None
                        else f'<img class="ts-dash-kpi-icon" src="{icon_data_uri(icon_file)}" alt="" />'
                    )
                    ok = kpi_ok[slug]
                    sub_icon = _CHECK_ICON if ok else _WARN_ICON
                    sub_class = "is-positive" if ok else "is-negative"
                    if ok is None:
                        sub_icon, sub_class = _WARN_ICON, "is-muted"
                    st.markdown(
                        f"""
                        <div class="ts-dash-kpi-head">
                          <span class="ts-dash-kpi-label">{label}</span>
                          {icon_html}
                        </div>
                        <p class="ts-dash-kpi-value">{_kpi_display(slug)}</p>
                        <p class="ts-dash-kpi-sub {sub_class}">{sub_icon}{kpi_sub[slug]}</p>
                        """,
                        unsafe_allow_html=True,
                    )

        table_col, bar_col = st.columns([1.6, 1], gap="small")

        with table_col:
            with st.container(key="ts_dash_report_table_card", border=True):
                rows = [
                    (label, kpi_goal_text[slug], kpi_values[slug], kpi_ok[slug])
                    for slug, label, _icon, _goal in _KPI_ROWS
                ]
                rows_html = "".join(
                    f'<div class="ts-report-row">'
                    f'<div class="ts-report-row-label">'
                    f'<span class="ts-report-row-title">{title}</span>'
                    f'<span class="ts-report-row-goal">{goal}</span>'
                    f"</div>"
                    f'<span class="ts-report-row-value">{"—" if value is None else f"{value:g}%"}</span>'
                    f'<span class="ts-report-row-target">{goal}</span>'
                    f'<span class="ts-report-status '
                    f'{"is-muted" if ok is None else ("is-ok" if ok else "is-warn")}">'
                    f'<span class="ts-report-status-dot"></span>'
                    f'{"판정 불가" if ok is None else ("달성" if ok else "미달")}'
                    f"</span>"
                    f"</div>"
                    for title, goal, value, ok in rows
                )
                st.markdown(
                    '<div class="ts-report-table">'
                    '<div class="ts-report-row ts-report-row-head">'
                    "<span>KPI 달성</span><span>측정값</span><span>목표</span><span>달성여부</span>"
                    "</div>"
                    f"{rows_html}"
                    "</div>",
                    unsafe_allow_html=True,
                )

        with bar_col:
            with st.container(key="ts_dash_report_bar_card", border=True):
                st.markdown(
                    '<p class="ts-dash-card-title">전력 사용량 비교'
                    '<span class="ts-report-bar-unit">kWh</span></p>',
                    unsafe_allow_html=True,
                )
                if real and not real.get("power_measured"):
                    # 스마트 플러그가 설치되기 전까지 전력 비교는 만들 수 없다.
                    # 그럴듯한 막대를 그리는 대신 무엇이 필요한지 알린다.
                    st.markdown(
                        '<div class="ts-report-empty">'
                        '<p>전력 실측 데이터가 없습니다.</p>'
                        '<p class="ts-report-empty-sub">스마트 플러그(plug 디바이스)를 설치하고 '
                        'baseline 구간을 수집하면 baseline·rule·predictive 비교가 표시됩니다.</p>'
                        "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    power_saving = kpi_values["power"] or 0
                    baseline_kwh = round(random.Random(f"{week_seed}-baseline").uniform(78, 90))
                    rule_kwh = round(baseline_kwh * random.Random(f"{week_seed}-rule").uniform(0.88, 0.95))
                    predictive_kwh = round(baseline_kwh * (1 - power_saving / 100))
                    bars = [("baseline", baseline_kwh, ""), ("rule", rule_kwh, ""), ("predictive", predictive_kwh, "is-highlight")]
                    max_kwh = max(v for _, v, _ in bars)
                    bars_html = "".join(
                        f'<div class="ts-report-bar-col">'
                        f'<span class="ts-report-bar-value">{value}</span>'
                        f'<div class="ts-report-bar {cls}" style="height:{max(6, round(value / max_kwh * 130))}px"></div>'
                        f'<span class="ts-report-bar-label">{label}</span>'
                        f"</div>"
                        for label, value, cls in bars
                    )
                    st.markdown(f'<div class="ts-report-bars">{bars_html}</div>', unsafe_allow_html=True)

        gauge_col, trend_col = st.columns([1, 2], gap="small")

        with gauge_col:
            with st.container(key="ts_dash_report_gauge_card", border=True):
                st.markdown('<p class="ts-dash-card-title">종합 쾌적도 지수</p>', unsafe_allow_html=True)
                circumference = 326.73
                dash = circumference * comfort_score / 100
                gauge_color = "var(--success)" if comfort_score >= 80 else "var(--warning)" if comfort_score >= 60 else "var(--danger)"
                gauge_label = "우수" if comfort_score >= 80 else "양호" if comfort_score >= 60 else "개선 필요"
                st.markdown(
                    f"""
                    <div class="ts-dash-gauge-wrap">
                      <svg viewBox="0 0 120 120" class="ts-dash-gauge-ring">
                        <circle cx="60" cy="60" r="52" stroke="var(--border)" stroke-width="14" fill="none" />
                        <circle cx="60" cy="60" r="52" stroke="{gauge_color}" stroke-width="14" fill="none"
                                stroke-linecap="round" stroke-dasharray="{dash:.2f} {circumference:.2f}"
                                transform="rotate(-90 60 60)" />
                      </svg>
                      <div class="ts-dash-gauge-center">
                        <span class="ts-dash-gauge-score">{comfort_score}</span>
                      </div>
                    </div>
                    <p class="ts-report-gauge-caption">이번주 평균 {gauge_label}</p>
                    """,
                    unsafe_allow_html=True,
                )

        with trend_col:
            with st.container(key="ts_dash_report_trend_card", border=True):
                st.markdown(
                    f'<p class="ts-dash-card-title">{_CHART_ICON}일별 쾌적도 지수 추이'
                    '<span class="ts-report-trend-sub">목표 80점 이상</span></p>',
                    unsafe_allow_html=True,
                )
                rnd = random.Random(f"{week_seed}-trend")
                n_points = 12
                value = comfort_score - rnd.uniform(4, 10)
                scores = []
                for _ in range(n_points - 1):
                    value += rnd.uniform(-1.5, 2.2)
                    scores.append(value)
                scores.append(float(comfort_score))
                days = [f"D{i + 1}" for i in range(n_points)]
                st.altair_chart(_trend_chart(days, scores, 80), width="stretch")

        # --- AI 분석 ---
        if ai_summary:
            with st.container(key="ts_dash_report_ai_card", border=True):
                st.markdown(
                    '<p class="ts-dash-card-title">AI 분석'
                    '<span class="ts-report-ai-badge">Claude</span></p>',
                    unsafe_allow_html=True,
                )
                sections = (
                    ("잘 된 점", ai_summary.get("highlights") or [], "is-positive"),
                    ("문제가 된 점", ai_summary.get("concerns") or [], "is-negative"),
                    ("다음 기간 할 일", ai_summary.get("recommendations") or [], "is-neutral"),
                )
                blocks = "".join(
                    f'<div class="ts-report-ai-section {cls}">'
                    f'<p class="ts-report-ai-heading">{heading}</p>'
                    f"<ul>{''.join(f'<li>{item}</li>' for item in items)}</ul>"
                    f"</div>"
                    for heading, items, cls in sections
                    if items
                )
                st.markdown(f'<div class="ts-report-ai">{blocks}</div>', unsafe_allow_html=True)
        elif report and report.get("ai_unavailable_reason"):
            with st.container(key="ts_dash_report_ai_card", border=True):
                st.markdown(
                    '<p class="ts-dash-card-title">AI 분석</p>'
                    f'<p class="ts-report-empty-sub">{report["ai_unavailable_reason"]}</p>',
                    unsafe_allow_html=True,
                )
