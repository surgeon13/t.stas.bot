"""Switchable backends for Overview / detail **line & bar charts** on the dashboard.

World maps stay Plotly; this module only abstracts line/bar visuals.
Selections are persisted as ``dashboard.chart_renderer`` in ``config/ui.yaml``.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ui_settings import VALID_CHART_BACKENDS


def normalize_chart_backend(key: str | None) -> str:
    k = (key or "plotly").strip().lower()
    return k if k in VALID_CHART_BACKENDS else "plotly"


def render_line_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
    backend: str,
) -> None:
    """Time-series chart (DatetimeIndex rows, one numeric column each)."""
    b = normalize_chart_backend(backend)
    if b == "streamlit":
        streamlit_line_chart(data, height=height)
        return
    if b == "altair":
        altair_line_chart(data, height=height, colorway=colorway)
        return
    plotly_line_chart(data, height=height, colorway=colorway)


def normalize_bar_kind(key: str | None) -> str:
    """``horizontal`` | ``vertical`` | ``dots`` (``ranked_table`` handled in dashboard)."""
    k = (key or "horizontal").strip().lower()
    if k == "ranked_table":
        return "ranked_table"
    return k if k in ("horizontal", "vertical", "dots") else "horizontal"


def render_bar_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
    backend: str,
    x_tick_angle: int = -35,
    bar_kind: str = "horizontal",
) -> None:
    """Categorical × one metric column: bars (H/V), strip dots, or streamlit/native."""
    kind = normalize_bar_kind(bar_kind)
    if kind == "ranked_table":
        return
    b = normalize_chart_backend(backend)
    if b == "streamlit" and kind == "vertical":
        streamlit_bar_chart(
            data.sort_values(data.columns[0], ascending=False), height=height
        )
        return
    # Horizontal / dots lack a good Streamlit primitive — reuse Plotly.
    if b == "streamlit":
        b = "plotly"
    if b == "altair":
        altair_bar_chart(
            data,
            height=height,
            colorway=colorway,
            x_tick_angle=x_tick_angle,
            bar_kind=kind,
        )
        return
    plotly_bar_chart(
        data,
        height=height,
        colorway=colorway,
        x_tick_angle=x_tick_angle,
        bar_kind=kind,
    )


# --- Plotly (default): full theme support ------------------------------------


def plotly_line_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
) -> None:
    if data is None or data.empty:
        return
    df = data.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    fig = go.Figure()
    palette = colorway
    for i, col in enumerate(df.columns):
        c = palette[i % len(palette)] if palette else None
        line = dict(width=2)
        if c:
            line["color"] = c
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                mode="lines",
                name=str(col),
                line=line,
            )
        )
    fig.update_layout(
        template="plotly_white",
        height=max(120, int(height)),
        margin=dict(l=40, r=16, t=36, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=True, title=""),
        yaxis=dict(showgrid=True, title=""),
    )
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


def plotly_bar_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
    x_tick_angle: int = -35,
    bar_kind: str = "horizontal",
) -> None:
    if data is None or data.empty:
        return
    kind = normalize_bar_kind(bar_kind)
    col = data.columns[0]
    ordered = data.sort_values(col, ascending=False)
    cats = [str(x) for x in ordered.index.tolist()]
    vals = list(ordered[col].tolist())
    n = len(vals)
    palette = colorway
    if palette:
        mcolors = [palette[i % len(palette)] for i in range(n)]
    else:
        mcolors = None

    if kind == "dots":
        fig = go.Figure(
            data=[
                go.Scatter(
                    x=vals,
                    y=cats,
                    mode="markers",
                    marker=dict(size=13, color=mcolors),
                )
            ]
        )
        fig.update_layout(
            template="plotly_white",
            height=max(120, int(height)),
            margin=dict(l=16, r=24, t=16, b=56),
            xaxis=dict(showgrid=True, title=str(col)),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
        return

    if kind == "horizontal":
        fig = go.Figure(
            data=[
                go.Bar(
                    x=vals,
                    y=cats,
                    orientation="h",
                    marker_color=mcolors,
                )
            ]
        )
        fig.update_layout(
            template="plotly_white",
            height=max(120, int(height)),
            margin=dict(l=16, r=24, t=16, b=56),
            xaxis=dict(showgrid=True, title=str(col)),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
        return

    # vertical columns
    fig = go.Figure(data=[go.Bar(x=cats, y=vals, marker_color=mcolors)])
    fig.update_layout(
        template="plotly_white",
        height=max(120, int(height)),
        margin=dict(l=40, r=16, t=12, b=120 if abs(x_tick_angle) > 20 else 48),
        xaxis=dict(tickangle=x_tick_angle, title=""),
        yaxis=dict(showgrid=True, title=str(col)),
    )
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})


# --- Streamlit built-in -------------------------------------------------------


def streamlit_line_chart(data: pd.DataFrame, *, height: int) -> None:
    if data is None or data.empty:
        return
    st.line_chart(data, width="stretch", height=max(120, int(height)))


def streamlit_bar_chart(data: pd.DataFrame, *, height: int) -> None:
    if data is None or data.empty:
        return
    st.bar_chart(data, width="stretch", height=max(120, int(height)))


# --- Altair / Vega-Lite ------------------------------------------------------


def altair_line_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
) -> None:
    if data is None or data.empty:
        return
    df = data.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df.index.name = "__t__"
    long_df = df.reset_index().melt(
        id_vars=["__t__"], var_name="series", value_name="value"
    )
    base = alt.Chart(long_df).mark_line()
    if colorway and len(colorway) > 0:
        cols = list(df.columns)
        rng = [colorway[i % len(colorway)] for i in range(len(cols))]
        chart = base.encode(
            x=alt.X("__t__:T", title=""),
            y=alt.Y("value:Q", title=""),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=cols, range=rng),
                legend=alt.Legend(orient="bottom"),
            ),
        ).properties(height=max(120, int(height)))
    else:
        chart = base.encode(
            x=alt.X("__t__:T", title=""),
            y=alt.Y("value:Q", title=""),
            color=alt.Color("series:N"),
        ).properties(height=max(120, int(height)))
    st.altair_chart(chart.interactive(), width="stretch")


def altair_bar_chart(
    data: pd.DataFrame,
    *,
    height: int,
    colorway: list[str] | None,
    x_tick_angle: int = -35,
    bar_kind: str = "horizontal",
) -> None:
    if data is None or data.empty:
        return
    kind = normalize_bar_kind(bar_kind)
    col = data.columns[0]
    ordered = data.sort_values(col, ascending=False)
    bdf = ordered[[col]].copy()
    bdf["__cat__"] = [str(x) for x in ordered.index.tolist()]
    sort_order = bdf["__cat__"].tolist()
    hue = (
        alt.Color(
            "__cat__:N",
            legend=None,
            scale=alt.Scale(
                domain=sort_order,
                range=[colorway[i % len(colorway)] for i in range(len(sort_order))],
            ),
        )
        if colorway and len(colorway) > 0
        else alt.Color("__cat__:N", legend=None)
    )

    if kind == "dots":
        chart = (
            alt.Chart(bdf)
            .mark_circle(size=90)
            .encode(
                x=alt.X(f"{col}:Q", title=str(col)),
                y=alt.Y("__cat__:N", title="", sort=sort_order),
                color=hue,
            )
            .properties(height=max(120, int(height)))
        )
        st.altair_chart(chart.interactive(), width="stretch")
        return

    if kind == "horizontal":
        chart = (
            alt.Chart(bdf)
            .mark_bar()
            .encode(
                x=alt.X(f"{col}:Q", title=str(col)),
                y=alt.Y("__cat__:N", sort=sort_order),
                color=hue,
            )
            .properties(height=max(120, int(height)))
        )
        st.altair_chart(chart.interactive(), width="stretch")
        return

    chart = (
        alt.Chart(bdf)
        .mark_bar()
        .encode(
            x=alt.X(
                "__cat__:N",
                title="",
                sort=sort_order,
                axis=alt.Axis(labelAngle=x_tick_angle),
            ),
            y=alt.Y(f"{col}:Q", title=str(col)),
            color=hue,
        )
        .properties(height=max(120, int(height)))
    )
    st.altair_chart(chart.interactive(), width="stretch")
