import base64
import re
from pathlib import Path

import streamlit as st

STYLE_ROOT = Path(__file__).resolve().parents[1] / "styles"
PAGE_STYLE_ROOT = STYLE_ROOT / "pages"
BASE_STYLESHEETS = (
    STYLE_ROOT / "tokens.css",
    STYLE_ROOT / "components.css",
)
ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"


def apply_mobile_styles(page_name: str, *, shared: tuple[str, ...] = ()) -> None:
    stylesheets = list(BASE_STYLESHEETS)
    for shared_name in shared:
        shared_stylesheet = PAGE_STYLE_ROOT / f"{shared_name}.css"
        if shared_stylesheet.exists():
            stylesheets.append(shared_stylesheet)
    page_stylesheet = PAGE_STYLE_ROOT / f"{page_name}.css"
    if page_stylesheet.exists():
        stylesheets.append(page_stylesheet)
    css = "\n".join(
        stylesheet.read_text(encoding="utf-8") for stylesheet in stylesheets
    )
    st.markdown(
        f"<style>{css}</style><div class='ts-page-marker ts-{page_name}'></div>",
        unsafe_allow_html=True,
    )


def page_header(title: str, back_page: str = "pages/onboarding.py") -> None:
    with st.container(key="ts_page_header"):
        st.page_link(back_page, label="‹")
        st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)


def auth_switch_link(
    page: str, label: str, *, key: str, prompt: str | None = None
) -> None:
    with st.container(key=key):
        if prompt:
            st.markdown(
                f'<span class="ts-single-link-prompt">{prompt}</span>',
                unsafe_allow_html=True,
            )
        st.page_link(page, label=label)


def inline_error(message: str) -> None:
    st.markdown(
        f'<p class="ts-field-error" role="alert">{message}</p>',
        unsafe_allow_html=True,
    )


_TAB_ITEMS = (
    ("home", "pages/home.py", "홈", "home.svg"),
    ("log", "pages/log_list.py", "제어로그", "receipt_long.svg"),
    ("alert", "pages/alert.py", "알림", "notifications.svg"),
    ("settings", "pages/settings.py", "설정", "settings.svg"),
)
_TAB_ACTIVE_COLOR = "#397f80"
_TAB_INACTIVE_COLOR = "#98a2b1"


def _tab_icon_data_uri(file_name: str, color: str) -> str:
    content = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    content = re.sub(r'fill="#[0-9A-Fa-f]{6}"', f'fill="{color}"', content)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def bottom_tab_bar(active: str) -> None:
    st.markdown('<div class="ts-tab-bar-spacer"></div>', unsafe_allow_html=True)
    icon_rules = []
    for tab_id, _page, _label, icon_file in _TAB_ITEMS:
        color = _TAB_ACTIVE_COLOR if tab_id == active else _TAB_INACTIVE_COLOR
        icon_uri = _tab_icon_data_uri(icon_file, color)
        icon_rules.append(
            f'.st-key-ts_tab_{tab_id} [data-testid="stPageLink"] a::before {{ '
            f'content: ""; display: block; width: 22px; height: 22px; '
            f'background-image: url("{icon_uri}"); background-repeat: no-repeat; '
            f"background-position: center; background-size: contain; }}"
        )
    active_text_rule = (
        f".st-key-ts_tab_{active} [data-testid=\"stPageLink\"] a "
        "{ color: var(--primary-dark) !important; }"
    )
    st.markdown(
        f"<style>{''.join(icon_rules)}{active_text_rule}</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="ts_tab_bar"):
        columns = st.columns(len(_TAB_ITEMS))
        for column, (tab_id, page, label, _icon_file) in zip(columns, _TAB_ITEMS):
            with column:
                with st.container(key=f"ts_tab_{tab_id}"):
                    st.page_link(page, label=label)
