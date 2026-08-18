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


def page_header(
    title: str, back_page: str = "main.py", *, show_back: bool = True
) -> None:
    with st.container(key="ts_page_header"):
        if show_back:
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


_MIME_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def icon_data_uri(file_name: str) -> str:
    path = ICONS_DIR / file_name
    mime = _MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def recolored_icon_data_uri(file_name: str, color: str) -> str:
    """Same as icon_data_uri but force-recolors an SVG's fills.

    Source icons are fill="#00696D" (dark teal) - fine on light rows, but
    invisible against dark sidebar/panel backgrounds, so callers that place
    icons on dark surfaces need a tinted variant instead of the raw asset.
    """
    content = (ICONS_DIR / file_name).read_text(encoding="utf-8")
    content = re.sub(r"<mask[^>]*>.*?</mask>", "", content, flags=re.DOTALL)
    content = re.sub(r'<[a-zA-Z]+[^>]*\smask="[^"]*"[^>]*/?>', "", content)
    content = re.sub(r'fill="(?!none"|white")[^"]*"', f'fill="{color}"', content)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def bottom_tab_bar(tabs: tuple[tuple[str, str, str], ...], active: str) -> None:
    """Renders a fixed bottom tab bar.

    tabs: tuple of (page_path, label, tab_id). Pass the concrete tab list
    from the page that calls this - there's no app-wide page set yet, so
    nothing is hardcoded here (unlike app/'s version, which has a fixed
    4-tab list because app/'s pages are already decided).
    """
    st.markdown('<div class="ts-tab-bar-spacer"></div>', unsafe_allow_html=True)
    with st.container(key="ts_tab_bar"):
        columns = st.columns(len(tabs))
        for column, (page, label, tab_id) in zip(columns, tabs):
            with column:
                with st.container(key=f"ts_tab_{tab_id}"):
                    st.page_link(page, label=label)
