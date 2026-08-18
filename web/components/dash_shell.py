import streamlit as st

from components.auth_store import current_user_email, current_user_name, log_out
from components.mobile_ui import icon_data_uri, recolored_icon_data_uri

_NAV_ICON_COLOR = "#ffffff"
_NAV_ICON_COLOR_MUTED = "rgba(255,255,255,0.4)"

# (id, label, icon file, target page or None for "not built yet" placeholders)
_NAV_SECTIONS = (
    (
        "운영",
        (
            ("dashboard", "대시보드", "home.svg", "pages/home.py"),
            ("room_detail", "공간 상세", "meeting_room.svg", "pages/room_detail.py"),
            ("digital_twin", "디지털 트윈·3D", "deployed_code.svg", "pages/digital_twin.py"),
            ("control_sim", "제어 시뮬레이션", "settings_remote.svg", None),
        ),
    ),
    (
        "기록",
        (
            ("control_log", "제어 로그", "receipt_long.svg", None),
            ("alerts", "알림", "notifications.svg", None),
            ("report", "성과 리포트", "monitoring.svg", None),
        ),
    ),
    (
        "관리",
        (("devices", "공간·디바이스", "sensors.svg", "pages/devices.py"),),
    ),
)


def render_sidebar(active: str) -> None:
    with st.container(key="ts_dash_sidebar"):
        st.markdown(
            f"""
            <div class="ts-dash-brand">
              <img src="{icon_data_uri("logo.svg")}" alt="" />
              <div>
                <span class="ts-dash-brand-name">Thermoshift</span>
                <span class="ts-dash-brand-sub">관리자 콘솔</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for section_title, items in _NAV_SECTIONS:
            st.markdown(f'<p class="ts-dash-nav-label">{section_title}</p>', unsafe_allow_html=True)
            for nav_id, label, icon_file, target in items:
                is_active = nav_id == active
                color = _NAV_ICON_COLOR if (is_active or target) else _NAV_ICON_COLOR_MUTED
                icon_uri = recolored_icon_data_uri(icon_file, color)
                disabled_class = "" if target else "is-disabled"
                if target and not is_active:
                    with st.container(key=f"ts_dash_nav_{nav_id}"):
                        st.markdown(
                            f"""
                            <div class="ts-dash-nav-item">
                              <img src="{icon_uri}" alt="" /><span>{label}</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if st.button(label, key=f"dash_nav_btn_{nav_id}", use_container_width=True):
                            st.switch_page(target)
                else:
                    active_class = "is-active" if is_active else ""
                    st.markdown(
                        f"""
                        <div class="ts-dash-nav-item {active_class} {disabled_class}">
                          <img src="{icon_uri}" alt="" /><span>{label}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        st.markdown('<div class="ts-dash-sidebar-spacer"></div>', unsafe_allow_html=True)

        with st.container(key="ts_dash_user_footer"):
            name = current_user_name() or "Thermoshift"
            email = current_user_email() or ""
            with st.container(key="ts_dash_user_link"):
                st.markdown(
                    f"""
                    <div class="ts-dash-user-row">
                      <div class="ts-dash-user-avatar">{name[:1].upper()}</div>
                      <div class="ts-dash-user-info">
                        <span class="ts-dash-user-name">{name}</span>
                        <span class="ts-dash-user-email">{email}</span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("프로필", key="dash_user_profile_btn", width="stretch"):
                    st.switch_page("pages/my_page.py")
            if st.button("로그아웃", key="dash_logout", width="stretch"):
                log_out()
                st.switch_page("pages/login.py")


def render_topbar(title: str, *, alert_count: int = 0) -> None:
    badge = f'<span class="ts-dash-topbar-badge">{alert_count}</span>' if alert_count else ""
    st.markdown(
        f"""
        <div class="ts-dash-topbar">
          <h1 class="ts-dash-topbar-title">{title}</h1>
          <div class="ts-dash-topbar-actions">
            <span class="ts-dash-topbar-icon">{_BELL_ICON}{badge}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


_BELL_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" '
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M6 10a6 6 0 1 1 12 0c0 3.4 1 5 1.5 5.5H4.5C5 15 6 13.4 6 10Z"/>'
    '<path d="M10 19.5a2 2 0 0 0 4 0"/></svg>'
)
