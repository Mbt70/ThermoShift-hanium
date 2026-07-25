import base64
from pathlib import Path

import streamlit as st


STYLE_ROOT = Path(__file__).resolve().parents[1] / "styles"
PAGE_STYLE_ROOT = STYLE_ROOT / "pages"
BASE_STYLESHEETS = (
    STYLE_ROOT / "tokens.css",
    STYLE_ROOT / "components.css",
)
LOGO = Path(__file__).resolve().parents[1] / "assets" / "icons" / "logo.svg"


def apply_mobile_styles(page_name: str) -> None:
    stylesheets = list(BASE_STYLESHEETS)
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


def brand_logo() -> None:
    encoded_logo = base64.b64encode(LOGO.read_bytes()).decode("ascii")
    st.markdown(
        f"""
        <div class="ts-logo" aria-label="ThermoShift 로고">
          <img src="data:image/svg+xml;base64,{encoded_logo}"
               alt="ThermoShift 로고">
        </div>
        """,
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
