"""Bullpen Signal — dashboard.

Scouting report aesthetic. Editorial layout, serif headers, monospace
numerics. Phase 0 renders against a synthetic narrative; Phase 1 wires
the same shapes to the live Kafka topics.

Run:
    streamlit run apps/dashboard/main.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import synthetic_data as sd
# ----------------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------------

st.set_page_config(
    page_title="Bullpen Signal",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ----------------------------------------------------------------------------
# Styling — the whole aesthetic lives in this block
# ----------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:wght@400;700&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@300;400;500;600&display=swap');

/* ---- page canvas -------------------------------------------------- */
.stApp {
    background: #F4EFE4 !important;
    background-image:
        radial-gradient(circle at 20% 10%, rgba(184, 114, 42, 0.03) 0%, transparent 40%),
        radial-gradient(circle at 80% 60%, rgba(26, 41, 71, 0.02) 0%, transparent 40%);
}
/* nuke the streamlit top bar completely */
header[data-testid="stHeader"] {
    background: transparent !important;
    height: 0 !important;
    visibility: hidden !important;
}
.stApp > header { background: transparent !important; display: none !important; }

/* give the page proper editorial margins */
.block-container {
    padding: 3rem 4rem 4rem 4rem !important;
    max-width: 1280px !important;
}
[data-testid="stAppViewContainer"] > .main {
    padding-top: 0 !important;
}

/* kill toolbar, menu, footer, deploy button */
#MainMenu, footer, .stDeployButton,
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] { visibility: hidden !important; display: none !important; }

/* ---- typography base ---------------------------------------------- */
html, body, [class*="css"] { color: #1A2947; }
h1, h2, h3, h4 {
    font-family: 'Libre Caslon Text', Georgia, serif !important;
    color: #1A2947 !important;
    letter-spacing: -0.01em;
}

/* ---- letterhead --------------------------------------------------- */
.letterhead {
    border-bottom: 3px double #1A2947;
    padding-bottom: 1.2rem;
    margin-bottom: 2rem;
}
.letterhead-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #6B5A3E;
    margin-bottom: 0.5rem;
}
.letterhead-title {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 3.2rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #1A2947;
    margin: 0.2rem 0 0.3rem 0;
}
.letterhead-sub {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-style: italic;
    font-size: 1.05rem;
    color: #4A5875;
    margin: 0;
}

/* ---- section headings --------------------------------------------- */
.section-head {
    display: flex;
    align-items: baseline;
    gap: 0.9rem;
    margin: 2rem 0 1rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #A89A7E;
}
.section-numeral {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 0.9rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: #B8722A;
}
.section-title {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 1.4rem;
    font-weight: 400;
    color: #1A2947;
    margin: 0;
}

/* ---- context strip (inning, score, outs) --------------------------- */
.context-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0;
    margin: 1rem 0 1.5rem 0;
    border: 1px solid #A89A7E;
    background: #FAF6EC;
}
.context-cell {
    padding: 0.9rem 1.1rem;
    border-right: 1px solid #D4C8AD;
}
.context-cell:last-child { border-right: none; }
.context-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #6B5A3E;
    margin-bottom: 0.3rem;
}
.context-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.35rem;
    font-weight: 500;
    color: #1A2947;
    letter-spacing: -0.02em;
}

/* ---- pitcher card ------------------------------------------------- */
.pitcher-card {
    background: #FAF6EC;
    border: 1px solid #A89A7E;
    padding: 1.5rem 1.8rem;
    margin-bottom: 0;
    position: relative;
}
.pitcher-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 4px;
    background: #1A2947;
}
.pitcher-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 1rem;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid #D4C8AD;
}
.pitcher-name {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 1.6rem;
    font-weight: 700;
    color: #1A2947;
    margin: 0;
}
.pitcher-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    color: #4A5875;
    letter-spacing: 0.02em;
}
.pitcher-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
}
.pstat-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #6B5A3E;
    margin-bottom: 0.2rem;
}
.pstat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.2rem;
    font-weight: 500;
    color: #1A2947;
}
.pstat-delta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: #8B2818;
    margin-top: 0.15rem;
}
.pstat-delta.positive { color: #2F5D3A; }

/* ---- alert card --------------------------------------------------- */
.alert-card {
    background: #1A2947;
    color: #F4EFE4;
    padding: 1.8rem 2rem;
    position: relative;
    overflow: hidden;
}
.alert-card.warning { background: #8B5A1A; }
.alert-card.action {
    background: #8B2818;
    box-shadow: inset 0 0 0 6px rgba(244, 239, 228, 0.08);
}
.alert-severity {
    display: inline-block;
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    padding: 0.35rem 0.9rem;
    border: 1px solid rgba(244, 239, 228, 0.4);
    margin-bottom: 1rem;
}
.alert-timestamp {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    opacity: 0.7;
    float: right;
    margin-top: 0.45rem;
}
.alert-rationale {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 1.4rem;
    font-weight: 400;
    line-height: 1.45;
    margin: 0.6rem 0 1.2rem 0;
    color: #F4EFE4;
}
.alert-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    opacity: 0.85;
    border-top: 1px solid rgba(244, 239, 228, 0.25);
    padding-top: 0.9rem;
    display: flex;
    gap: 2rem;
    flex-wrap: wrap;
}
.alert-meta span strong { font-weight: 700; }

/* ---- signals panel ------------------------------------------------ */
.signals-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    margin: 0.6rem 0 1.5rem 0;
}
.signal-tile {
    background: #FAF6EC;
    border: 1px solid #A89A7E;
    padding: 1.1rem 1.2rem;
    position: relative;
}
.signal-tile-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.5rem;
}
.signal-name {
    font-family: 'Inter', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #6B5A3E;
}
.signal-status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
}
.signal-status-dot.info { background: #B8722A; }
.signal-status-dot.warning { background: #C7700F; }
.signal-status-dot.action { background: #8B2818; }
.signal-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2rem;
    font-weight: 500;
    color: #1A2947;
    letter-spacing: -0.03em;
    line-height: 1;
    margin-bottom: 0.3rem;
}
.signal-caption {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-style: italic;
    font-size: 0.88rem;
    color: #4A5875;
    line-height: 1.4;
}

/* ---- prose paragraph ---------------------------------------------- */
.analysis {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 1.02rem;
    line-height: 1.65;
    color: #2C3A56;
    column-count: 2;
    column-gap: 2.5rem;
    margin: 0.6rem 0 1.5rem 0;
    text-align: justify;
}
.analysis::first-letter {
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 3rem;
    font-weight: 700;
    float: left;
    line-height: 0.9;
    margin: 0.2rem 0.35rem 0 0;
    color: #1A2947;
}

/* ---- reconciliation table ---------------------------------------- */
.recon-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.88rem;
    background: #FAF6EC;
    border: 1px solid #A89A7E;
    margin: 1rem 0 1.5rem 0;
}
.recon-table thead th {
    font-family: 'Inter', sans-serif;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #6B5A3E;
    padding: 0.85rem 1rem;
    text-align: left;
    border-bottom: 2px solid #1A2947;
    background: #F4EFE4;
}
.recon-table tbody td {
    padding: 0.7rem 1rem;
    border-bottom: 1px solid #E0D5B8;
    color: #1A2947;
}
.recon-table tbody tr:last-child td { border-bottom: none; }
.recon-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.recon-class {
    font-family: 'Inter', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 0.22rem 0.6rem;
    border: 1px solid currentColor;
    display: inline-block;
}
.recon-class.confirmed { color: #2F5D3A; }
.recon-class.softened { color: #8B5A1A; }
.recon-class.reversed { color: #8B2818; }
.recon-class.escalated { color: #6B2D78; }
.recon-class.confirmed_late { color: #4A5875; }

/* ---- footer rule -------------------------------------------------- */
.footer-rule {
    border-top: 1px solid #A89A7E;
    margin-top: 3rem;
    padding-top: 1rem;
    font-family: 'Inter', sans-serif;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6B5A3E;
    display: flex;
    justify-content: space-between;
}

/* ---- tabs restyle -------------------------------------------------- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 2px solid #A89A7E;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: #6B5A3E !important;
    padding: 0.9rem 1.5rem !important;
    background: transparent !important;
    border-bottom: 3px solid transparent !important;
    margin-bottom: -2px !important;
}
.stTabs [aria-selected="true"] {
    color: #1A2947 !important;
    border-bottom-color: #B8722A !important;
}

/* stamp for FINAL watermark on canonical tab */
.watermark-final {
    position: absolute;
    top: 120px; right: 60px;
    font-family: 'Libre Caslon Text', Georgia, serif;
    font-size: 4rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: rgba(139, 40, 24, 0.07);
    transform: rotate(-12deg);
    pointer-events: none;
    z-index: 1;
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Data load
# ----------------------------------------------------------------------------

ctx = sd.game_context()
pitcher = sd.active_pitcher()
pitches = sd.pitch_log()
signals = sd.streaming_signals()
alerts_list = sd.alerts()
recon = sd.reconciliation_rows()


# ----------------------------------------------------------------------------
# Letterhead
# ----------------------------------------------------------------------------

st.markdown(
    f"""
<div class="letterhead">
  <div class="letterhead-top">
    <div>Bullpen Signal · Advance Report</div>
    <div>{ctx.game_date} · Game #{ctx.game_pk} · Page 1 of 1</div>
  </div>
  <h1 class="letterhead-title">Bullpen Signal</h1>
  <p class="letterhead-sub">A dual-path decision engine for pitcher fatigue, bullpen readiness, and matchup leverage.</p>
</div>
""",
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

tab_live, tab_canon, tab_recon = st.tabs(
    ["I · Live dugout", "II · Canonical truth", "III · Reconciliation"]
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _fatigue_line_chart(signals_data, *, highlight_pitch: int | None = None) -> go.Figure:
    xs = [s.pitch_idx for s in signals_data]
    ys = [s.fatigue for s in signals_data]
    ls = [s.leverage for s in signals_data]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys,
            mode="lines",
            line=dict(color="#1A2947", width=2.6),
            name="fatigue",
            hovertemplate="pitch %{x}<br>fatigue %{y:.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs, y=[v / 3.5 for v in ls],
            mode="lines",
            line=dict(color="#B8722A", width=1.8, dash="dot"),
            name="leverage (scaled)",
            hovertemplate="pitch %{x}<br>leverage %{customdata:.2f}<extra></extra>",
            customdata=ls,
        )
    )
    # threshold lines without clashing annotations inside plot
    fig.add_hline(y=0.55, line=dict(color="#C7700F", width=1, dash="dash"))
    fig.add_hline(y=0.70, line=dict(color="#8B2818", width=1.4, dash="dash"))
    # put threshold labels on the right side, outside the chart area
    fig.add_annotation(
        x=1.005, y=0.55, xref="paper", yref="y",
        text="warning 0.55", showarrow=False,
        font=dict(family="JetBrains Mono", size=10, color="#C7700F"),
        xanchor="left", yanchor="middle",
    )
    fig.add_annotation(
        x=1.005, y=0.70, xref="paper", yref="y",
        text="action 0.70", showarrow=False,
        font=dict(family="JetBrains Mono", size=10, color="#8B2818"),
        xanchor="left", yanchor="middle",
    )
    if highlight_pitch:
        fig.add_vline(x=highlight_pitch, line=dict(color="#8B2818", width=1.4))
        fig.add_annotation(
            x=highlight_pitch, y=1.02, xref="x", yref="paper",
            text=f"alert · pitch {highlight_pitch}", showarrow=False,
            font=dict(family="JetBrains Mono", size=10, color="#8B2818"),
            xanchor="center", yanchor="bottom",
        )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FAF6EC",
        font=dict(family="JetBrains Mono", size=11, color="#1A2947"),
        margin=dict(l=50, r=130, t=50, b=50),
        height=360,
        xaxis=dict(
            title=dict(text="pitch #", font=dict(size=10, color="#6B5A3E")),
            showgrid=True, gridcolor="#E0D5B8", zeroline=False,
            tickfont=dict(color="#4A5875"),
        ),
        yaxis=dict(
            title="",
            showgrid=True, gridcolor="#E0D5B8", zeroline=False,
            range=[0.15, 0.95],
            tickfont=dict(color="#4A5875"),
            tickvals=[0.2, 0.4, 0.55, 0.7, 0.8],
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.08, xanchor="left", x=0,
            font=dict(family="Inter", size=10, color="#6B5A3E"),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor="#FAF6EC",
            font_family="JetBrains Mono",
            font_color="#1A2947",
            bordercolor="#1A2947",
        ),
    )
    return fig


def _velocity_chart(pitch_data) -> go.Figure:
    xs = [p.pitch_idx for p in pitch_data]
    ys = [p.velo for p in pitch_data]
    baseline = sum(p.velo for p in pitch_data[:20]) / 20

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs, y=ys,
            mode="markers",
            marker=dict(size=7, color="#1A2947", opacity=0.5,
                        line=dict(color="#FAF6EC", width=0.8)),
            name="velocity",
            hovertemplate="pitch %{x}<br>%{y:.1f} mph<extra></extra>",
        )
    )
    # rolling mean
    window = 10
    rolling = []
    for i in range(len(ys)):
        start = max(0, i - window + 1)
        rolling.append(sum(ys[start : i + 1]) / (i - start + 1))
    fig.add_trace(
        go.Scatter(
            x=xs, y=rolling,
            mode="lines",
            line=dict(color="#B8722A", width=2.4),
            name="10-pitch rolling avg",
            hovertemplate="pitch %{x}<br>rolling %{y:.1f} mph<extra></extra>",
        )
    )
    fig.add_hline(y=baseline, line=dict(color="#4A5875", width=1, dash="dot"))
    fig.add_annotation(
        x=1.005, y=baseline, xref="paper", yref="y",
        text=f"baseline {baseline:.1f}",
        showarrow=False,
        font=dict(family="JetBrains Mono", size=10, color="#4A5875"),
        xanchor="left", yanchor="middle",
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FAF6EC",
        font=dict(family="JetBrains Mono", size=11, color="#1A2947"),
        margin=dict(l=50, r=130, t=50, b=50),
        height=320,
        xaxis=dict(
            title=dict(text="pitch #", font=dict(size=10, color="#6B5A3E")),
            showgrid=True, gridcolor="#E0D5B8", zeroline=False,
            tickfont=dict(color="#4A5875"),
        ),
        yaxis=dict(
            title=dict(text="mph", font=dict(size=10, color="#6B5A3E")),
            showgrid=True, gridcolor="#E0D5B8", zeroline=False,
            tickfont=dict(color="#4A5875"),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.08, xanchor="left", x=0,
            font=dict(family="Inter", size=10, color="#6B5A3E"),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor="#FAF6EC",
            font_family="JetBrains Mono",
            font_color="#1A2947",
            bordercolor="#1A2947",
        ),
    )
    return fig


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S UTC")


# ----------------------------------------------------------------------------
# Tab I — Live dugout
# ----------------------------------------------------------------------------

with tab_live:
    current_pitch = 92
    current_signal = next(s for s in signals if s.pitch_idx == current_pitch)
    active_alert = alerts_list[-1]  # the action-level one

    # Context strip
    st.markdown(
        f"""
<div class="section-head">
  <span class="section-numeral">§ I</span>
  <h2 class="section-title">Situational context</h2>
</div>
<div class="context-strip">
  <div class="context-cell">
    <div class="context-label">Inning</div>
    <div class="context-value">7 · Top</div>
  </div>
  <div class="context-cell">
    <div class="context-label">Score</div>
    <div class="context-value">{ctx.away_team} 3 — {ctx.home_team} 2</div>
  </div>
  <div class="context-cell">
    <div class="context-label">Bases / Outs</div>
    <div class="context-value">1st, 2nd · 1 out</div>
  </div>
  <div class="context-cell">
    <div class="context-label">Count · Pitch #</div>
    <div class="context-value">2-2 · {current_pitch}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Alert hero + pitcher card
    c1, c2 = st.columns([1.35, 1])

    with c1:
        st.markdown(
            f"""
<div class="section-head">
  <span class="section-numeral">§ II</span>
  <h2 class="section-title">Active alert</h2>
</div>
<div class="alert-card {active_alert.severity}">
  <span class="alert-severity">· {active_alert.severity} ·</span>
  <span class="alert-timestamp">emitted {_fmt_time(active_alert.emitted_time)}</span>
  <p class="alert-rationale">{active_alert.rationale}</p>
  <div class="alert-meta">
    <span><strong>composite score</strong> &nbsp; {active_alert.composite_score:.2f}
      <span style="opacity:.6">/ {active_alert.threshold:.2f}</span></span>
    <span><strong>inputs snapshot</strong> &nbsp; {active_alert.inputs_uid}</span>
    <span><strong>alert uid</strong> &nbsp; {active_alert.alert_uid}</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    with c2:
        velo_delta = current_signal.fatigue_velocity_component
        spin_delta = current_signal.fatigue_spin_component
        cmd_delta = current_signal.fatigue_command_component

        st.markdown(
            f"""
<div class="section-head">
  <span class="section-numeral">§ III</span>
  <h2 class="section-title">Active pitcher</h2>
</div>
<div class="pitcher-card">
  <div class="pitcher-heading">
    <h3 class="pitcher-name">{pitcher.name}</h3>
    <div class="pitcher-meta">#{pitcher.jersey} · {pitcher.throws}HP · {pitcher.team}</div>
  </div>
  <div class="pitcher-stats">
    <div>
      <div class="pstat-label">Pitches</div>
      <div class="pstat-value">{current_pitch}</div>
      <div class="pstat-delta">7.0 IP · 3 ER</div>
    </div>
    <div>
      <div class="pstat-label">Velo (avg)</div>
      <div class="pstat-value">91.8</div>
      <div class="pstat-delta">-2.5 vs first 20</div>
    </div>
    <div>
      <div class="pstat-label">Spin</div>
      <div class="pstat-value">2135</div>
      <div class="pstat-delta">-177 vs baseline</div>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    # Signals tile row
    st.markdown(
        f"""
<div class="section-head">
  <span class="section-numeral">§ IV</span>
  <h2 class="section-title">Signals, as streaming sees them</h2>
</div>
<div class="signals-grid">
  <div class="signal-tile">
    <div class="signal-tile-head">
      <span class="signal-name">Fatigue</span>
      <span class="signal-status-dot action"></span>
    </div>
    <div class="signal-value">{current_signal.fatigue:.2f}</div>
    <div class="signal-caption">Past action threshold of 0.70. Driven chiefly by velocity component ({velo_delta:.2f}) and command drop ({cmd_delta:.2f}).</div>
  </div>
  <div class="signal-tile">
    <div class="signal-tile-head">
      <span class="signal-name">Leverage</span>
      <span class="signal-status-dot warning"></span>
    </div>
    <div class="signal-value">{current_signal.leverage:.2f}</div>
    <div class="signal-caption">Runner in scoring position, one-run game, late innings. Every out is disproportionately valuable.</div>
  </div>
  <div class="signal-tile">
    <div class="signal-tile-head">
      <span class="signal-name">Matchup edge</span>
      <span class="signal-status-dot warning"></span>
    </div>
    <div class="signal-value">{current_signal.matchup_edge:+.3f}</div>
    <div class="signal-caption">Expected wOBA allowed vs. next confirmed batter. Negative is favorable; the margin has compressed over the last fifteen pitches.</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Analysis prose
    st.markdown(
        """
<div class="section-head">
  <span class="section-numeral">§ V</span>
  <h2 class="section-title">Analysis</h2>
</div>
<p class="analysis">
Through five innings this was a clean outing. The first twenty-pitch baseline sat at ninety-four and a half with spin holding steady near the season average, and command was crisp enough to work the edges without walking himself into trouble.
The slide began quietly in the sixth, the kind of degradation that does not show up in a box score until the runs already scored. Velocity drifted down two ticks, the breaking ball lost separation, and the zone percentage dipped from the mid-sixties to the low fifties.
By the seventh it was unambiguous. The composite score has crossed the action threshold, leverage is elevated with men on, and the next batter owns a strong profile against a tiring fastball. Streaming has done its job. The question now is what batch will say in four hours and whether it will agree.
</p>
""",
        unsafe_allow_html=True,
    )

    # Charts
    st.markdown(
        """
<div class="section-head">
  <span class="section-numeral">§ VI</span>
  <h2 class="section-title">Trajectories</h2>
</div>
""",
        unsafe_allow_html=True,
    )

    st.plotly_chart(
        _fatigue_line_chart(signals, highlight_pitch=current_pitch),
        use_container_width=True,
        config={"displayModeBar": False},
    )
    st.plotly_chart(
        _velocity_chart(pitches),
        use_container_width=True,
        config={"displayModeBar": False},
    )


# ----------------------------------------------------------------------------
# Tab II — Canonical truth
# ----------------------------------------------------------------------------

with tab_canon:
    st.markdown('<div class="watermark-final">FINAL</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
<div class="section-head">
  <span class="section-numeral">§ I</span>
  <h2 class="section-title">Canonical game record</h2>
</div>
<p class="analysis" style="column-count: 1;">
This is what batch recomputed three hours and twelve minutes after the final out, once late-arriving pitches were reconciled, one pitch-type classification was corrected by MLB official scoring, and season splits were joined in full. The numbers here are the reference against which every streaming signal above is measured.
</p>
""",
        unsafe_allow_html=True,
    )

    canon_pitcher = sd.active_pitcher()
    st.markdown(
        f"""
<div class="pitcher-card" style="margin-bottom: 1.5rem;">
  <div class="pitcher-heading">
    <h3 class="pitcher-name">{canon_pitcher.name} &nbsp;
      <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 400; color: #8B2818; letter-spacing: 0.1em;">
      · FINAL LINE ·</span>
    </h3>
    <div class="pitcher-meta">#{canon_pitcher.jersey} · {canon_pitcher.throws}HP · {canon_pitcher.team}</div>
  </div>
  <div class="pitcher-stats" style="grid-template-columns: repeat(5, 1fr);">
    <div>
      <div class="pstat-label">IP</div>
      <div class="pstat-value">6.2</div>
    </div>
    <div>
      <div class="pstat-label">Pitches</div>
      <div class="pstat-value">98</div>
    </div>
    <div>
      <div class="pstat-label">H · ER</div>
      <div class="pstat-value">7 · 4</div>
    </div>
    <div>
      <div class="pstat-label">K · BB</div>
      <div class="pstat-value">5 · 3</div>
    </div>
    <div>
      <div class="pstat-label">Final velo</div>
      <div class="pstat-value">91.2</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div class="section-head">
  <span class="section-numeral">§ II</span>
  <h2 class="section-title">Canonical fatigue curve</h2>
</div>
""",
        unsafe_allow_html=True,
    )
    # Canonical version: slightly different values
    canon_signals = [
        sd.SignalSnapshot(
            event_time=s.event_time,
            pitch_idx=s.pitch_idx,
            fatigue=round(s.fatigue + 0.03 if s.pitch_idx > 70 else s.fatigue - 0.01, 3),
            fatigue_velocity_component=s.fatigue_velocity_component,
            fatigue_spin_component=s.fatigue_spin_component,
            fatigue_command_component=s.fatigue_command_component,
            leverage=s.leverage,
            matchup_edge=s.matchup_edge,
        )
        for s in signals
    ]
    st.plotly_chart(
        _fatigue_line_chart(canon_signals),
        use_container_width=True,
        config={"displayModeBar": False},
    )


# ----------------------------------------------------------------------------
# Tab III — Reconciliation
# ----------------------------------------------------------------------------

with tab_recon:
    st.markdown(
        """
<div class="section-head">
  <span class="section-numeral">§ I</span>
  <h2 class="section-title">Where streaming met canonical truth</h2>
</div>
<p class="analysis" style="column-count: 1;">
Every alert emitted by the streaming orchestrator is joined against the batch-canonical value for its component signals at the same game state. The delta is recorded with an outcome classification. Across this game the orchestrator fired three alerts; batch confirmed all three directional calls, softened one matchup component, and made no reversals. The action-level replace call held.
</p>
""",
        unsafe_allow_html=True,
    )

    # Render the reconciliation table
    rows_html = []
    for r in recon:
        delta_class = "positive" if r.delta >= 0 else "negative"
        sign = "+" if r.delta >= 0 else ""
        rows_html.append(f"""
<tr>
  <td style="font-size: 0.78rem; color: #6B5A3E;">{r.alert_uid}</td>
  <td>{r.signal}</td>
  <td class="num">{r.streaming_value:+.3f}</td>
  <td class="num">{r.canonical_value:+.3f}</td>
  <td class="num">{sign}{r.delta:.3f}</td>
  <td><span class="recon-class {r.classification}">{r.classification.replace('_', ' ')}</span></td>
</tr>""")

    st.markdown(
        f"""
<table class="recon-table">
  <thead>
    <tr>
      <th>Alert</th>
      <th>Signal</th>
      <th style="text-align: right;">Streaming</th>
      <th style="text-align: right;">Canonical</th>
      <th style="text-align: right;">Δ</th>
      <th>Classification</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
</table>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div class="section-head">
  <span class="section-numeral">§ II</span>
  <h2 class="section-title">Classification legend</h2>
</div>
<div class="signals-grid" style="grid-template-columns: repeat(5, 1fr);">
  <div class="signal-tile">
    <div class="signal-name" style="margin-bottom: 0.3rem;"><span class="recon-class confirmed">confirmed</span></div>
    <div class="signal-caption">Batch agreed with the streaming call.</div>
  </div>
  <div class="signal-tile">
    <div class="signal-name" style="margin-bottom: 0.3rem;"><span class="recon-class confirmed_late">confirmed late</span></div>
    <div class="signal-caption">Batch would have fired the same alert, slower.</div>
  </div>
  <div class="signal-tile">
    <div class="signal-name" style="margin-bottom: 0.3rem;"><span class="recon-class softened">softened</span></div>
    <div class="signal-caption">Lower severity on the canonical side.</div>
  </div>
  <div class="signal-tile">
    <div class="signal-name" style="margin-bottom: 0.3rem;"><span class="recon-class escalated">escalated</span></div>
    <div class="signal-caption">Batch would have called it more serious.</div>
  </div>
  <div class="signal-tile">
    <div class="signal-name" style="margin-bottom: 0.3rem;"><span class="recon-class reversed">reversed</span></div>
    <div class="signal-caption">Batch disagreed. Streaming was wrong.</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# Footer
# ----------------------------------------------------------------------------

st.markdown(
    f"""
<div class="footer-rule">
  <span>Bullpen Signal · Phase 0 · Synthetic narrative</span>
  <span>Rendered {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</span>
</div>
""",
    unsafe_allow_html=True,
)
