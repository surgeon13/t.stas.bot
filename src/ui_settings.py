"""UI preferences shared by the Streamlit dashboard and the CLI menu.

Map palettes are stored in ``config/ui.yaml`` (by default) so terminal
settings and the dashboard stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


import yaml

DEFAULT_UI_PATH = Path("config") / "ui.yaml"

# (canvas, axis, village dots, highlight fill, highlight outline, highlight radius px)
@dataclass(frozen=True)
class MapPalette:
    key: str
    title: str
    bg: tuple[int, int, int]
    axis: tuple[int, int, int]
    dot: tuple[int, int, int]
    hl_fill: tuple[int, int, int]
    hl_outline: tuple[int, int, int]
    hl_radius: int = 6


MAP_PALETTES: tuple[MapPalette, ...] = (
    MapPalette(
        "parchment",
        "Parchment — light, easy to read (default)",
        bg=(245, 235, 220),
        axis=(140, 120, 95),
        dot=(55, 50, 45),
        hl_fill=(210, 45, 35),
        hl_outline=(255, 255, 255),
        hl_radius=6,
    ),
    MapPalette(
        "paper",
        "Paper — white / slate / orange",
        bg=(252, 252, 250),
        axis=(100, 110, 125),
        dot=(70, 85, 105),
        hl_fill=(230, 120, 20),
        hl_outline=(255, 255, 255),
        hl_radius=6,
    ),
    MapPalette(
        "high_contrast",
        "High contrast — black dots on white",
        bg=(255, 255, 255),
        axis=(0, 0, 0),
        dot=(15, 15, 15),
        hl_fill=(0, 90, 200),
        hl_outline=(255, 255, 0),
        hl_radius=7,
    ),
    MapPalette(
        "ocean",
        "Ocean — teal canvas / cyan villages",
        bg=(18, 52, 64),
        axis=(80, 140, 150),
        dot=(160, 220, 235),
        hl_fill=(255, 140, 90),
        hl_outline=(20, 20, 30),
        hl_radius=6,
    ),
    MapPalette(
        "midnight",
        "Midnight — original dark / grey / red",
        bg=(16, 18, 22),
        axis=(70, 75, 90),
        dot=(200, 205, 220),
        hl_fill=(255, 70, 70),
        hl_outline=(255, 255, 255),
        hl_radius=6,
    ),
)

_PALETTE_BY_KEY: dict[str, MapPalette] = {p.key: p for p in MAP_PALETTES}


@dataclass(frozen=True)
class DashAppTheme:
    """Global dashboard chrome (Streamlit shell) — backgrounds, text, tab bar."""

    key: str
    title: str
    appearance: Literal["light", "dark"]
    page_bg: str
    sidebar_bg: str
    sidebar_border: str
    header_bg: str
    text_body: str
    text_muted: str
    link_color: str
    metric_value: str
    tab_gradient_top: str
    tab_gradient_bot: str
    tab_border: str
    tab_tray_shadow: str
    tab_text: str
    tab_hover_bg: str
    tab_selected_bg: str
    tab_selected_ring: str
    tab_focus_ring: str
    toolbar_divider: str
    scrollbar_thumb: str
    alert_soft_bg: str


DASH_APP_THEMES: tuple[DashAppTheme, ...] = (
    DashAppTheme(
        key="slate_warm",
        title="Slate & warm — muted grays, easy on the eyes (recommended)",
        appearance="light",
        page_bg="#e8ecf1",
        sidebar_bg="#dfe5ed",
        sidebar_border="#c8d2e0",
        header_bg="rgba(232, 236, 241, 0.94)",
        text_body="#15202b",
        text_muted="#5c6b7c",
        link_color="#3d5a80",
        metric_value="#0f172a",
        tab_gradient_top="#d5dde8",
        tab_gradient_bot="#cdd6e3",
        tab_border="#b4c0d1",
        tab_tray_shadow=(
            "0 1px 2px rgba(15, 23, 42, 0.07), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.45)"
        ),
        tab_text="#4a5b6c",
        tab_hover_bg="rgba(255, 255, 255, 0.5)",
        tab_selected_bg="rgba(61, 90, 128, 0.14)",
        tab_selected_ring="rgba(61, 90, 128, 0.28)",
        tab_focus_ring="rgba(61, 90, 128, 0.42)",
        toolbar_divider="#b8c6d6",
        scrollbar_thumb="#94a8bc",
        alert_soft_bg="rgba(255, 255, 255, 0.42)",
    ),
    DashAppTheme(
        key="sage_canvas",
        title="Sage canvas — soft green-gray fields (long sessions)",
        appearance="light",
        page_bg="#e6ebe3",
        sidebar_bg="#dae3d6",
        sidebar_border="#b9c8b2",
        header_bg="rgba(230, 235, 227, 0.94)",
        text_body="#192119",
        text_muted="#4d5c49",
        link_color="#2f5d40",
        metric_value="#142818",
        tab_gradient_top="#cdd8c8",
        tab_gradient_bot="#c5d1c0",
        tab_border="#aabda3",
        tab_tray_shadow=(
            "0 1px 2px rgba(25, 33, 25, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.38)"
        ),
        tab_text="#4a5f44",
        tab_hover_bg="rgba(255, 255, 255, 0.45)",
        tab_selected_bg="rgba(47, 93, 64, 0.16)",
        tab_selected_ring="rgba(47, 93, 64, 0.3)",
        tab_focus_ring="rgba(47, 93, 64, 0.45)",
        toolbar_divider="#a3b89a",
        scrollbar_thumb="#8faa85",
        alert_soft_bg="rgba(255, 255, 255, 0.38)",
    ),
    DashAppTheme(
        key="paper_clay",
        title="Paper & clay — warm ivory / terracotta tint",
        appearance="light",
        page_bg="#efe8df",
        sidebar_bg="#e6dbd0",
        sidebar_border="#d1c2b4",
        header_bg="rgba(239, 232, 223, 0.94)",
        text_body="#2a1810",
        text_muted="#705a4d",
        link_color="#a8432c",
        metric_value="#1c0f0a",
        tab_gradient_top="#ddd0c3",
        tab_gradient_bot="#d4c5b6",
        tab_border="#c4b0a0",
        tab_tray_shadow=(
            "0 1px 2px rgba(42, 24, 16, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.4)"
        ),
        tab_text="#5c4a3e",
        tab_hover_bg="rgba(255, 255, 255, 0.48)",
        tab_selected_bg="rgba(168, 67, 44, 0.15)",
        tab_selected_ring="rgba(168, 67, 44, 0.28)",
        tab_focus_ring="rgba(168, 67, 44, 0.42)",
        toolbar_divider="#c9b8a9",
        scrollbar_thumb="#b09784",
        alert_soft_bg="rgba(255, 252, 247, 0.55)",
    ),
    DashAppTheme(
        key="arctic_blue",
        title="Arctic blue — airy cool studio",
        appearance="light",
        page_bg="#e6eef8",
        sidebar_bg="#dae8f5",
        sidebar_border="#b9cee8",
        header_bg="rgba(230, 238, 248, 0.94)",
        text_body="#122030",
        text_muted="#4a667d",
        link_color="#1d6aa0",
        metric_value="#0a1624",
        tab_gradient_top="#c9daf0",
        tab_gradient_bot="#bfd3ec",
        tab_border="#9ebad8",
        tab_tray_shadow=(
            "0 1px 2px rgba(18, 32, 48, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.5)"
        ),
        tab_text="#3d5870",
        tab_hover_bg="rgba(255, 255, 255, 0.55)",
        tab_selected_bg="rgba(29, 106, 160, 0.13)",
        tab_selected_ring="rgba(29, 106, 160, 0.28)",
        tab_focus_ring="rgba(29, 106, 160, 0.42)",
        toolbar_divider="#a3bcdb",
        scrollbar_thumb="#7a9fc4",
        alert_soft_bg="rgba(255, 255, 255, 0.45)",
    ),
    DashAppTheme(
        key="royal_blue",
        title="Royal blue — cobalt headers, sapphire gradient tabs",
        appearance="light",
        page_bg="#e4ebfb",
        sidebar_bg="#d7e1f9",
        sidebar_border="#a8bfea",
        header_bg="rgba(228, 235, 251, 0.94)",
        text_body="#0f172a",
        text_muted="#475569",
        link_color="#1e40af",
        metric_value="#020617",
        tab_gradient_top="#b8cbf5",
        tab_gradient_bot="#a9bff2",
        tab_border="#7c96de",
        tab_tray_shadow=(
            "0 1px 2px rgba(15, 23, 42, 0.07), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.5)"
        ),
        tab_text="#334155",
        tab_hover_bg="rgba(255, 255, 255, 0.55)",
        tab_selected_bg="rgba(30, 64, 175, 0.16)",
        tab_selected_ring="rgba(30, 64, 175, 0.32)",
        tab_focus_ring="rgba(37, 99, 235, 0.5)",
        toolbar_divider="#94a9e6",
        scrollbar_thumb="#6b83d6",
        alert_soft_bg="rgba(248, 250, 255, 0.55)",
    ),
    DashAppTheme(
        key="graphite_grey",
        title="Graphite grey — neutral zinc studio, smoky tab stripe",
        appearance="light",
        page_bg="#ececee",
        sidebar_bg="#e2e4e9",
        sidebar_border="#c6cad3",
        header_bg="rgba(236, 236, 238, 0.94)",
        text_body="#18181b",
        text_muted="#52525c",
        link_color="#3f3f46",
        metric_value="#09090b",
        tab_gradient_top="#d4d6dd",
        tab_gradient_bot="#cbcdd5",
        tab_border="#a1a7b3",
        tab_tray_shadow=(
            "0 1px 2px rgba(24, 24, 27, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.45)"
        ),
        tab_text="#3f3f46",
        tab_hover_bg="rgba(255, 255, 255, 0.5)",
        tab_selected_bg="rgba(63, 63, 70, 0.12)",
        tab_selected_ring="rgba(63, 63, 70, 0.28)",
        tab_focus_ring="rgba(39, 39, 42, 0.45)",
        toolbar_divider="#b4b8c2",
        scrollbar_thumb="#71717b",
        alert_soft_bg="rgba(250, 250, 250, 0.72)",
    ),
    DashAppTheme(
        key="lavender_mist",
        title="Lavender mist — lilac veil, violet gradient rails",
        appearance="light",
        page_bg="#f1ecfa",
        sidebar_bg="#e8e2f6",
        sidebar_border="#cdc0eb",
        header_bg="rgba(241, 236, 250, 0.94)",
        text_body="#1e1b2e",
        text_muted="#5b5675",
        link_color="#5b21b6",
        metric_value="#14121f",
        tab_gradient_top="#ddd0ec",
        tab_gradient_bot="#d4c5e8",
        tab_border="#b8a3df",
        tab_tray_shadow=(
            "0 1px 2px rgba(30, 27, 46, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.52)"
        ),
        tab_text="#4c4768",
        tab_hover_bg="rgba(255, 255, 255, 0.55)",
        tab_selected_bg="rgba(91, 33, 182, 0.14)",
        tab_selected_ring="rgba(109, 40, 217, 0.3)",
        tab_focus_ring="rgba(124, 58, 237, 0.48)",
        toolbar_divider="#c4aed9",
        scrollbar_thumb="#9575c9",
        alert_soft_bg="rgba(255, 253, 255, 0.55)",
    ),
    DashAppTheme(
        key="peach_horizon",
        title="Peach horizon — apricot blush, warm sunset fade",
        appearance="light",
        page_bg="#fdf0e8",
        sidebar_bg="#fce7dc",
        sidebar_border="#f0cbb8",
        header_bg="rgba(253, 240, 232, 0.94)",
        text_body="#2a1410",
        text_muted="#6b5348",
        link_color="#b45309",
        metric_value="#1c0f0c",
        tab_gradient_top="#ffd7c7",
        tab_gradient_bot="#ffcbb5",
        tab_border="#e8a892",
        tab_tray_shadow=(
            "0 1px 2px rgba(42, 20, 16, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.55)"
        ),
        tab_text="#5d4438",
        tab_hover_bg="rgba(255, 255, 255, 0.55)",
        tab_selected_bg="rgba(180, 83, 9, 0.14)",
        tab_selected_ring="rgba(180, 83, 9, 0.3)",
        tab_focus_ring="rgba(194, 65, 12, 0.45)",
        toolbar_divider="#e0b099",
        scrollbar_thumb="#c4886e",
        alert_soft_bg="rgba(255, 252, 248, 0.65)",
    ),
    DashAppTheme(
        key="emerald_grove",
        title="Emerald grove — teal mist, rainforest gradient stripe",
        appearance="light",
        page_bg="#e8f3ef",
        sidebar_bg="#d9eae3",
        sidebar_border="#b5d5c8",
        header_bg="rgba(232, 243, 239, 0.94)",
        text_body="#0f2922",
        text_muted="#3f534c",
        link_color="#047857",
        metric_value="#051f19",
        tab_gradient_top="#c2dfd3",
        tab_gradient_bot="#b5d9cb",
        tab_border="#8fc4b4",
        tab_tray_shadow=(
            "0 1px 2px rgba(15, 41, 34, 0.06), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.48)"
        ),
        tab_text="#35574d",
        tab_hover_bg="rgba(255, 255, 255, 0.5)",
        tab_selected_bg="rgba(4, 120, 87, 0.14)",
        tab_selected_ring="rgba(5, 150, 105, 0.3)",
        tab_focus_ring="rgba(13, 148, 136, 0.45)",
        toolbar_divider="#9bbfb2",
        scrollbar_thumb="#6b9988",
        alert_soft_bg="rgba(247, 253, 250, 0.55)",
    ),
    DashAppTheme(
        key="rose_quartz",
        title="Rose quartz — dusk pink / mauve gradient shell",
        appearance="light",
        page_bg="#f8eef4",
        sidebar_bg="#f3e5ee",
        sidebar_border="#e0cadb",
        header_bg="rgba(248, 238, 244, 0.94)",
        text_body="#2d1526",
        text_muted="#6b5663",
        link_color="#9d174d",
        metric_value="#1a0f16",
        tab_gradient_top="#e9d4e1",
        tab_gradient_bot="#e4cad9",
        tab_border="#d1b4c7",
        tab_tray_shadow=(
            "0 1px 2px rgba(45, 21, 38, 0.05), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.55)"
        ),
        tab_text="#5e4a54",
        tab_hover_bg="rgba(255, 255, 255, 0.52)",
        tab_selected_bg="rgba(157, 23, 77, 0.12)",
        tab_selected_ring="rgba(157, 23, 77, 0.28)",
        tab_focus_ring="rgba(190, 24, 93, 0.42)",
        toolbar_divider="#cdb4c7",
        scrollbar_thumb="#a67f92",
        alert_soft_bg="rgba(255, 250, 252, 0.6)",
    ),
    DashAppTheme(
        key="obsidian_data",
        title="Obsidian data — dark UI, high contrast tables & metrics",
        appearance="dark",
        page_bg="#11141a",
        sidebar_bg="#161a22",
        sidebar_border="#2a3140",
        header_bg="rgba(17, 20, 26, 0.92)",
        text_body="#e6e9f0",
        text_muted="#9aa3b7",
        link_color="#7ab8ff",
        metric_value="#f1f4fa",
        tab_gradient_top="#242a36",
        tab_gradient_bot="#1c222d",
        tab_border="#3d4759",
        tab_tray_shadow=(
            "0 4px 18px rgba(0, 0, 0, 0.45), "
            "inset 0 1px 0 rgba(255, 255, 255, 0.05)"
        ),
        tab_text="#b4bfd4",
        tab_hover_bg="rgba(255, 255, 255, 0.07)",
        tab_selected_bg="rgba(122, 184, 255, 0.14)",
        tab_selected_ring="rgba(122, 184, 255, 0.35)",
        tab_focus_ring="rgba(122, 184, 255, 0.55)",
        toolbar_divider="#3d4759",
        scrollbar_thumb="#5a667c",
        alert_soft_bg="rgba(36, 42, 54, 0.65)",
    ),
)

_DASH_APP_THEME_BY_KEY: dict[str, DashAppTheme] = {t.key: t for t in DASH_APP_THEMES}
VALID_DASH_APP_THEMES: tuple[str, ...] = tuple(t.key for t in DASH_APP_THEMES)
LIGHT_DASH_APP_THEMES: tuple[str, ...] = tuple(t.key for t in DASH_APP_THEMES if t.appearance == "light")
DARK_SHELL_THEME_KEY: str = "obsidian_data"
VALID_SHELL_APPEARANCE: tuple[str, ...] = ("light", "dark")


def normalize_light_app_theme_key(key: str | None) -> str:
    k = (key or "").strip().lower()
    if k in LIGHT_DASH_APP_THEMES:
        return k
    return LIGHT_DASH_APP_THEMES[0] if LIGHT_DASH_APP_THEMES else "slate_warm"


def effective_shell_theme_slug(*, appearance: str, light_app_theme: str | None) -> str:
    """Resolve injected CSS palette: Dark → obsidian shell; Light → chosen light preset."""
    a = (appearance or "light").strip().lower()
    if a == "dark":
        return DARK_SHELL_THEME_KEY
    return normalize_light_app_theme_key(light_app_theme)



def get_dash_app_theme(key: str | None) -> DashAppTheme:
    k = (key or "").strip()
    if k not in _DASH_APP_THEME_BY_KEY:
        k = "slate_warm"
    return _DASH_APP_THEME_BY_KEY[k]


def build_dashboard_shell_css(theme: DashAppTheme) -> str:
    """CSS for Streamlit chrome; injected once per rerun via ``st.markdown``."""
    scheme = "dark" if theme.appearance == "dark" else "light"

    metric_opacity = "0.92" if theme.appearance == "dark" else "0.95"

    return f"""
<style id="dash-app-theme-css">
  :root {{
    --dash-page-bg: {theme.page_bg};
    --dash-sidebar-bg: {theme.sidebar_bg};
    --dash-sidebar-border: {theme.sidebar_border};
    --dash-header-bg: {theme.header_bg};
    --dash-text-body: {theme.text_body};
    --dash-text-muted: {theme.text_muted};
    --dash-link: {theme.link_color};
    --dash-metric-val: {theme.metric_value};
  }}

  .stApp {{
    color-scheme: {scheme};
    background-color: var(--dash-page-bg) !important;
    color: var(--dash-text-body) !important;
  }}

  [data-testid="stAppViewContainer"] {{
    background-color: var(--dash-page-bg) !important;
  }}

  section[data-testid="stMain"] {{
    background-color: var(--dash-page-bg) !important;
  }}

  [data-testid="stToolbar"],
  header[data-testid="stHeader"] {{
    background: var(--dash-header-bg) !important;
    backdrop-filter: blur(10px);
  }}

  /* Sidebar: Streamlit ≥1.30 uses ``section[data-testid="stSidebar"]``; inner divs inherit theme solid bg */
  section[data-testid="stSidebar"],
  div[data-testid="stSidebar"] {{
    background-color: var(--dash-sidebar-bg) !important;
    background: var(--dash-sidebar-bg) !important;
    border-right: 1px solid var(--dash-sidebar-border) !important;
  }}
  section[data-testid="stSidebar"] > div,
  div[data-testid="stSidebar"] > div {{
    background-color: var(--dash-sidebar-bg) !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
  section[data-testid="stSidebar"] .block-container,
  div[data-testid="stSidebar"] [data-testid="stSidebarContent"],
  div[data-testid="stSidebar"] .block-container {{
    background-color: var(--dash-sidebar-bg) !important;
  }}
  section[data-testid="stSidebarHeader"],
  header[data-testid="stSidebarHeader"],
  [data-testid="stSidebarHeader"] {{
    background-color: transparent !important;
    background: transparent !important;
    border-bottom: 1px solid var(--dash-sidebar-border);
  }}

  section[data-testid="stSidebar"] label,
  div[data-testid="stSidebar"] label {{
    color: var(--dash-text-muted) !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
  div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{
    color: var(--dash-text-body) !important;
  }}

  section[data-testid="stMain"] .block-container,
  section[data-testid="stMain"] .block-container > div {{ background: transparent !important; }}

  .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span[style] {{
    color: inherit;
  }}
  .main .block-container h1, .main .block-container h2, .main .block-container h3,
  .main .block-container h4, .main .block-container h5, .main .block-container h6 {{
    color: var(--dash-text-body) !important;
  }}
  .main .block-container a, [data-testid="stMarkdownContainer"] a {{
    color: var(--dash-link) !important;
  }}

  [data-testid="stCaption"],
  div[data-testid="stCaption"] {{ color: var(--dash-text-muted) !important; }}

  label[data-testid], [data-testid="stWidgetLabel"],
  span[data-testid="stMarkdown"] + div label {{
    color: var(--dash-text-muted) !important;
  }}

  div[data-testid="metric-container"] div[data-testid="stMarkdownContainer"] {{
    color: var(--dash-metric-val) !important;
  }}
  div[data-testid="metric-container"] label {{
    color: var(--dash-text-muted) !important;
    opacity: {metric_opacity} !important;
  }}

  div[data-testid="stSidebarNav"] + div:not([data-testid]),
  div[data-testid="stDecoration"] {{ display: none !important; }}
  footer {{ visibility: hidden; }}

  .block-container {{
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 1480px;
  }}

  section[data-testid="stSidebar"] hr,
  div[data-testid="stSidebar"] hr {{ margin-top: .75rem; margin-bottom: .75rem; }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"],
  div[data-testid="stTabs"] [role="tablist"] {{
    gap: 6px !important;
    padding: 8px 10px !important;
    background: linear-gradient(
      180deg,
      {theme.tab_gradient_top} 0%,
      {theme.tab_gradient_bot} 100%
    ) !important;
    backdrop-filter: blur(10px);
    border: 1px solid {theme.tab_border} !important;
    border-radius: 14px !important;
    box-shadow: {theme.tab_tray_shadow} !important;
    flex-wrap: nowrap !important;
    overflow-x: auto !important;
    overflow-y: hidden !important;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    scrollbar-color: {theme.scrollbar_thumb} transparent;
    margin-bottom: 1.25rem !important;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar,
  div[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar {{ height: 5px; }}
  div[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar-thumb,
  div[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar-thumb {{
    background: {theme.scrollbar_thumb};
    border-radius: 10px;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"] button,
  div[data-testid="stTabs"] [role="tablist"] button {{
    border: none !important;
    border-radius: 10px !important;
    padding: 0.45rem 0.9rem !important;
    margin: 0 !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em !important;
    color: {theme.tab_text} !important;
    background: transparent !important;
    white-space: nowrap !important;
    line-height: 1.35 !important;
    min-height: 2.35rem !important;
    transition: background 0.12s ease, color 0.12s ease, box-shadow 0.12s ease !important;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"] button:hover,
  div[data-testid="stTabs"] [role="tablist"] button:hover {{
    background: {theme.tab_hover_bg} !important;
    color: var(--dash-text-body) !important;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"] button[aria-selected="true"],
  div[data-testid="stTabs"] [role="tablist"] button[aria-selected="true"] {{
    background: {theme.tab_selected_bg} !important;
    color: var(--dash-text-body) !important;
    font-weight: 600 !important;
    box-shadow: inset 0 0 0 1px {theme.tab_selected_ring} !important;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-list"] button:focus-visible,
  div[data-testid="stTabs"] [role="tablist"] button:focus-visible {{
    outline: 2px solid {theme.tab_focus_ring} !important;
    outline-offset: 2px !important;
  }}

  div[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none !important; }}
  div[data-testid="stTabs"] [data-baseweb="tab-panel"] {{ padding-top: 0.15rem !important; }}

  .dash-toolbar-divider {{
    height: 1px;
    margin: 1.2rem 0 0.75rem;
    background: linear-gradient(
      90deg,
      transparent,
      {theme.toolbar_divider} 6%,
      {theme.toolbar_divider} 94%,
      transparent
    );
  }}

  div[data-testid="stDataFrame"] {{ border-radius: 10px !important; }}

  h2 {{ font-weight: 600 !important; letter-spacing: -0.02em; }}
  div[data-testid="stAlert"] {{
    border-radius: 10px !important;
    border: none !important;
    background-color: {theme.alert_soft_bg} !important;
  }}
</style>
""".strip()


VALID_CHART_SIZES: tuple[str, ...] = ("compact", "comfortable", "spacious")
VALID_CHART_BACKENDS: tuple[str, ...] = (
    "plotly",
    "streamlit",
    "altair",
)
VALID_CHART_COLORS: tuple[str, ...] = (
    "default",
    "muted",
    "ocean",
    "warm",
    "cool",
    "colorblind",
    "royal",
    "mist_grey",
    "twilight",
    "forest_edge",
)

# Overview “Tribe distribution” & “Top alliances” (not line charts over time).
VALID_OVERVIEW_BAR_KINDS: tuple[str, ...] = (
    "horizontal",  # bars left→right (readable labels; default)
    "vertical",    # classic upright columns
    "dots",        # dot / strip plot — no heavy bars
    "ranked_table",  # sortable table, no chart
)


@dataclass(frozen=True)
class ChartSizePreset:
    """Pixel heights for dashboards (charts + maps) by overall size preset."""

    detail_line: int
    overview_line: int
    overview_bar: int
    embedded_map: int
    full_map: int


CHART_SIZE_PRESETS: dict[str, ChartSizePreset] = {
    "compact": ChartSizePreset(150, 200, 200, 320, 520),
    "comfortable": ChartSizePreset(220, 280, 250, 440, 640),
    "spacious": ChartSizePreset(300, 400, 320, 560, 800),
}


# Applied to Plotly line/bar graphs (dashboard charts). ``None`` = Plotly default palette.
_CHART_COLOR_THEMES: dict[str, list[str] | None] = {
    "default": None,
    "muted": [
        "#516f90",
        "#6b8e6f",
        "#c4965c",
        "#9178aa",
        "#b86775",
        "#4f9aaf",
        "#8f7ab8",
        "#71907a",
    ],
    "ocean": [
        "#0ea5e9",
        "#06b6d4",
        "#14b8a6",
        "#0284c7",
        "#22d3ee",
        "#2dd4bf",
        "#38bdf8",
        "#67e8f9",
    ],
    "warm": [
        "#c2410c",
        "#ca8a04",
        "#b91c1c",
        "#a16207",
        "#ea580c",
        "#d97706",
        "#dc2626",
        "#eab308",
    ],
    "cool": [
        "#2563eb",
        "#7c3aed",
        "#0d9488",
        "#4f46e5",
        "#0ea5e9",
        "#6366f1",
        "#0891b2",
        "#8b5cf6",
    ],
    "colorblind": [
        "#0173e2",
        "#de8f05",
        "#029e73",
        "#cc78bc",
        "#ca9161",
        "#949494",
        "#ece133",
        "#56b4e9",
    ],
    "royal": [
        "#172554",
        "#1e40af",
        "#2563eb",
        "#3b82f6",
        "#4f46e5",
        "#6366f1",
        "#7c82f6",
        "#93c5fd",
    ],
    "mist_grey": [
        "#3f3f46",
        "#52525b",
        "#64748b",
        "#71717a",
        "#78716c",
        "#91959c",
        "#a8a29e",
        "#cbd5e1",
    ],
    "twilight": [
        "#581c87",
        "#6b21a8",
        "#7c3aed",
        "#8b5cf6",
        "#a78bfa",
        "#c084fc",
        "#d946ef",
        "#e879f9",
    ],
    "forest_edge": [
        "#064e3b",
        "#047857",
        "#059669",
        "#0d9488",
        "#0f766e",
        "#14804b",
        "#16a34a",
        "#4ade80",
    ],
}


def resolve_chart_preset(key: str | None) -> ChartSizePreset:
    k = (key or "").strip().lower()
    if k not in CHART_SIZE_PRESETS:
        k = "compact"
    return CHART_SIZE_PRESETS[k]


def chart_graph_colorway(chart_colors_key: str | None) -> list[str] | None:
    """Return color list for Plotly graphs, or None for library defaults."""
    k = (chart_colors_key or "").strip().lower()
    if k not in _CHART_COLOR_THEMES:
        k = "muted"
    return _CHART_COLOR_THEMES[k]


@dataclass
class UISettings:
    map_palette: str = "parchment"
    chart_size: str = "compact"
    chart_colors: str = "muted"
    chart_renderer: str = "plotly"
    overview_bar_kind: str = "horizontal"
    app_theme: str = "slate_warm"
    appearance: str = "light"


def get_palette(key: str | None) -> MapPalette:
    if key and key in _PALETTE_BY_KEY:
        return _PALETTE_BY_KEY[key]
    return _PALETTE_BY_KEY["parchment"]


def load_ui_settings(path: str | Path | None = None) -> UISettings:
    p = Path(path) if path else DEFAULT_UI_PATH
    if not p.exists():
        return UISettings()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    dash = raw.get("dashboard") or {}
    pal = str(dash.get("map_palette", "parchment")).strip()
    if pal not in _PALETTE_BY_KEY:
        pal = "parchment"
    cs = str(dash.get("chart_size", "compact")).strip().lower()
    if cs not in VALID_CHART_SIZES:
        cs = "compact"
    cc = str(dash.get("chart_colors", "muted")).strip().lower()
    if cc not in VALID_CHART_COLORS:
        cc = "muted"
    cr = str(dash.get("chart_renderer", "plotly")).strip().lower()
    if cr not in VALID_CHART_BACKENDS:
        cr = "plotly"
    obk = str(dash.get("overview_bar_kind", "horizontal")).strip().lower()
    if obk not in VALID_OVERVIEW_BAR_KINDS:
        obk = "horizontal"
    ath = str(dash.get("app_theme", "slate_warm")).strip().lower()
    if ath == DARK_SHELL_THEME_KEY:
        ath = normalize_light_app_theme_key("slate_warm")
    else:
        ath = normalize_light_app_theme_key(ath)

    ap = str(dash.get("appearance", "")).strip().lower()
    if ap not in VALID_SHELL_APPEARANCE:
        ap = (
            "dark"
            if str(dash.get("app_theme", "")).strip().lower() == DARK_SHELL_THEME_KEY
            else "light"
        )
    return UISettings(
        map_palette=pal,
        chart_size=cs,
        chart_colors=cc,
        chart_renderer=cr,
        overview_bar_kind=obk,
        app_theme=ath,
        appearance=ap,
    )


def save_ui_settings(settings: UISettings, path: str | Path | None = None) -> None:
    p = Path(path) if path else DEFAULT_UI_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any]
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    raw.setdefault("dashboard", {})
    if not isinstance(raw["dashboard"], dict):
        raw["dashboard"] = {}
    raw["dashboard"]["map_palette"] = settings.map_palette
    raw["dashboard"]["chart_size"] = settings.chart_size
    raw["dashboard"]["chart_colors"] = settings.chart_colors
    raw["dashboard"]["chart_renderer"] = settings.chart_renderer
    raw["dashboard"]["overview_bar_kind"] = settings.overview_bar_kind
    raw["dashboard"]["app_theme"] = settings.app_theme
    raw["dashboard"]["appearance"] = settings.appearance
    p.write_text(yaml.safe_dump(raw, default_flow_style=False, sort_keys=False), encoding="utf-8")


def cycle_map_palette(current: str) -> str:
    keys = [p.key for p in MAP_PALETTES]
    try:
        i = keys.index(current)
    except ValueError:
        i = 0
    return keys[(i + 1) % len(keys)]
