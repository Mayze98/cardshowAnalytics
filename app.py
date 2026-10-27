"""
Card Show Analytics: a dashboard for Collectr exports.

Reads one Collectr inventory export plus any number of Collectr transaction log
exports (one per card show) and shows realized and unrealized profit, expenses,
and analytics. Data is kept in Google Sheets when credentials are set in Streamlit
secrets, otherwise in the local data folder (see storage.py).

Run:  streamlit run app.py
"""

from __future__ import annotations

import hmac
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from storage import get_store, show_name_from_file

# --------------------------------------------------------------------------
# Paths and settings
# --------------------------------------------------------------------------
EXPENSE_CATEGORIES = ["Table fee", "Gas / travel", "Hotel", "Food", "Parking",
                      "Supplies", "Payment fees", "Grading", "Other"]

# Palette
INK = "#1C2430"
MUTED = "#6B7486"
GRID = "#E6E9EF"
GAIN = "#1F8A70"
LOSS = "#C8424F"
INDIGO = "#33449E"
SERIES = ["#33449E", "#5C6FD6", "#9AA6EC", "#1F8A70", "#7CC2AE",
          "#D9A441", "#C8424F", "#A3AABA", "#2C7DA0", "#B36A8F"]

st.set_page_config(page_title="Card Show Analytics", page_icon="🃏", layout="wide")

# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
.stApp, .stApp p, .stApp li, .stApp label, .stApp h1, .stApp h2, .stApp h3,
.stApp h4, .stApp button p, .stApp input {{
  font-family: 'Manrope', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}
.stApp h3 {{ font-size: 1.3rem; font-weight: 700; }}
.hero {{ padding: 0.2rem 0 1.4rem; border-bottom: 1px solid {GRID}; }}
.hero-label {{ color: {MUTED}; font-size: 0.95rem; font-weight: 500; margin: 0; }}
.hero-number {{ font-size: clamp(2.6rem, 6vw, 4.4rem); font-weight: 800;
  letter-spacing: -0.04em; line-height: 1.02; margin: 0.15rem 0 0.4rem;
  font-variant-numeric: tabular-nums; }}
.hero-number.gain {{ color: {GAIN}; }}
.hero-number.loss {{ color: {LOSS}; }}
.hero-sentence {{ max-width: 70ch; color: #3A4352; font-size: 1.05rem; line-height: 1.55; margin: 0; }}
.hero-note {{ color: {MUTED}; font-size: 0.85rem; margin-top: 0.6rem; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  margin: 0.4rem 0 1.6rem; }}
.stat {{ padding: 1rem 1rem 1rem 0; border-bottom: 1px solid {GRID}; }}
.stat-value {{ font-size: 1.4rem; font-weight: 700; color: {INK};
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }}
.stat-key {{ font-size: 0.84rem; color: {MUTED}; margin-top: 0.1rem; }}
.stat-sub {{ font-size: 0.8rem; font-weight: 600; margin-top: 0.15rem; }}
.stat-sub.gain {{ color: {GAIN}; }} .stat-sub.loss {{ color: {LOSS}; }}
.stat-sub.flat {{ color: {MUTED}; }}
.section-note {{ color: {MUTED}; font-size: 0.88rem; margin: -0.4rem 0 0.8rem; }}
div[data-testid="stTabs"] button p {{ font-size: 0.98rem; font-weight: 600; }}
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def to_num(series: pd.Series) -> pd.Series:
    """'1,442.97' -> 1442.97 ; blanks -> NaN."""
    cleaned = series.astype(str).str.replace(r"[,$\s]", "", regex=True)
    out = pd.to_numeric(cleaned.replace({"": np.nan, "nan": np.nan}), errors="coerce")
    # Always plain float64, whatever backend pandas picked (Arrow, nullable, object)
    return pd.Series(pd.array(out).to_numpy(dtype="float64", na_value=np.nan), index=series.index)


def expenses_by_show(df: pd.DataFrame, shows: pd.Series) -> pd.Series:
    """Total expenses for each show in `shows`, as plain floats (0 when none)."""
    totals: dict[str, float] = {}
    for show, amount in zip(df["Show"].astype(str), to_num(df["Amount"]).fillna(0.0)):
        totals[show] = totals.get(show, 0.0) + float(amount)
    return pd.Series([totals.get(str(s_), 0.0) for s_ in shows], index=shows.index, dtype="float64")


def money(x: float, signed: bool = False, decimals: int = 0) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    sign = ""
    if x < 0:
        sign = "−"
    elif signed and x > 0:
        sign = "+"
    return f"{sign}${abs(x):,.{decimals}f}"


def pct(x: float, signed: bool = True) -> str:
    if x is None or np.isnan(x) or np.isinf(x):
        return "–"
    sign = "+" if (signed and x > 0) else ("−" if x < 0 else "")
    return f"{sign}{abs(x) * 100:.1f}%"


def tone(x: float) -> str:
    if x is None or np.isnan(x) or abs(x) < 0.005:
        return "flat"
    return "gain" if x > 0 else "loss"


def shorten(text: str, limit: int = 42) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def grade_group(grade: str) -> str:
    """'PSA 10.0 GEM - MT' -> 'PSA 10'; 'Ungraded' -> 'Raw'."""
    g = str(grade).strip()
    if not g or g.lower() == "ungraded":
        return "Raw"
    m = re.match(r"([A-Za-z]+)\s+([\d.]+)", g)
    if m:
        return f"{m.group(1).upper()} {float(m.group(2)):g}"
    return g


def style_fig(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=44, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, system-ui, sans-serif", color=INK, size=13),
        title=dict(font=dict(size=15, color=INK), x=0, xanchor="left"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0, title=None),
        hoverlabel=dict(font_family="Manrope, system-ui, sans-serif"),
    )
    fig.update_xaxes(automargin=True, showgrid=False, linecolor=GRID, tickcolor=GRID, title_font_color=MUTED)
    fig.update_traces(insidetextorientation="horizontal", selector=dict(type="pie"))
    money_axis = lambda a: a.update(tickprefix="", tickformat="$,.0f") if a.tickprefix == "$" else None
    fig.for_each_xaxis(money_axis)
    fig.for_each_yaxis(money_axis)
    fig.update_yaxes(automargin=True, gridcolor=GRID, zerolinecolor="#C9CED8", linecolor=GRID, title_font_color=MUTED)
    return fig


def show_chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, theme=None)


def empty(msg: str) -> None:
    st.info(msg)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def parse_inventory(raw: bytes) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    original = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                           engine="python", index_col=False)
    original.columns = [c.strip() for c in original.columns]
    cols = {c.lower(): c for c in original.columns}

    def col(name: str, default: str = "") -> pd.Series:
        key = cols.get(name.lower())
        return original[key] if key else pd.Series([default] * len(original))

    market_col = next((c for c in original.columns if c.lower().startswith("market price")), None)
    as_of = ""
    if market_col:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", market_col)
        as_of = m.group(1) if m else ""

    df = pd.DataFrame({
        "Portfolio": col("Portfolio Name").str.strip(),
        "Game": col("Category").str.strip(),
        "Set": col("Set").str.strip(),
        "Card": col("Product Name").str.strip(),
        "Number": col("Card Number"),
        "Rarity": col("Rarity"),
        "Variant": col("Variance"),
        "Grade": col("Grade").replace("", "Ungraded"),
        "Condition": col("Card Condition"),
        "Unit cost": to_num(col("Average Cost Paid", "0")).fillna(0),
        "Qty": to_num(col("Quantity", "1")).fillna(1),
        "Unit market": to_num(original[market_col]) if market_col else np.nan,
        "Override": to_num(col("Price Override", "0")).fillna(0),
        "Date added": pd.to_datetime(col("Date Added"), errors="coerce"),
    })
    # Price override wins; a market price of 0 means Collectr has no data.
    df["Unit value"] = np.where(df["Override"] > 0, df["Override"],
                                np.where(df["Unit market"] > 0, df["Unit market"], np.nan))
    df["Has value"] = df["Unit value"].notna()
    df["Cost"] = df["Unit cost"] * df["Qty"]
    df["Market value"] = df["Unit value"] * df["Qty"]
    df["Unrealized"] = df["Market value"] - df["Cost"]
    df["Return"] = np.where(df["Cost"] > 0, df["Unrealized"] / df["Cost"], np.nan)
    df["Zero cost"] = df["Unit cost"] <= 0
    df["Type"] = np.where(df["Grade"].str.lower() == "ungraded", "Raw", "Graded")
    df["Grade group"] = df["Grade"].map(grade_group)
    df["Label"] = (df["Card"] + " (" + df["Set"] + ")").map(shorten)
    return df, original, as_of


@st.cache_data(show_spinner=False)
def parse_sales(raw: bytes, show: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    original = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                           engine="python", index_col=False)
    original.columns = [c.strip() for c in original.columns]
    cols = {c.lower(): c for c in original.columns}

    def col(name: str, default: str = "") -> pd.Series:
        key = cols.get(name.lower())
        return original[key] if key else pd.Series([default] * len(original))

    df = pd.DataFrame({
        "Show": show,
        "Portfolio": col("Portfolio Name").str.strip(),
        "Card": col("Product Name").str.strip(),
        "Variant": col("Product Subtype"),
        "Grade": col("Grade").replace("", "Ungraded"),
        "Condition": col("Card Condition"),
        "Qty": to_num(col("Quantity", "1")).fillna(1),
        "Unit cost": to_num(col("Purchase Price", "0")).fillna(0),
        "Unit price": to_num(col("Sold Price", "0")).fillna(0),
        "Bought": pd.to_datetime(col("Purchase Date"), errors="coerce"),
        "Sold": pd.to_datetime(col("Sold Date"), errors="coerce"),
    })
    df["Cost"] = df["Unit cost"] * df["Qty"]
    df["Revenue"] = df["Unit price"] * df["Qty"]
    df["Realized"] = df["Revenue"] - df["Cost"]
    df["Margin"] = np.where(df["Revenue"] > 0, df["Realized"] / df["Revenue"], np.nan)
    df["Days held"] = (df["Sold"] - df["Bought"]).dt.days
    df["Zero cost"] = df["Unit cost"] <= 0
    df["Type"] = np.where(df["Grade"].str.lower() == "ungraded", "Raw", "Graded")
    df["Grade group"] = df["Grade"].map(grade_group)
    df["Label"] = (df["Card"] + " (" + df["Grade group"] + ")").map(shorten)
    return df, original


# --------------------------------------------------------------------------
# Optional password (set app_password in Streamlit secrets)
# --------------------------------------------------------------------------
def app_password() -> str | None:
    try:
        return st.secrets.get("app_password")
    except Exception:  # noqa: BLE001
        return None


if app_password() and not st.session_state.get("signed_in"):
    st.title("Card Show Analytics")
    with st.form("sign_in"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Open dashboard", type="primary"):
            if hmac.compare_digest(entered, str(app_password())):
                st.session_state["signed_in"] = True
                st.rerun()
            else:
                st.error("That password isn't right. Try again.")
    st.stop()

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
store = get_store()
if store.kind == "sheets":
    try:
        store.check()
    except Exception as e:  # noqa: BLE001
        st.title("Card Show Analytics")
        st.error(
            "Couldn't open your Google Sheet. Check that `spreadsheet_url` in the app's secrets "
            f"is right and that the sheet is shared with **{store.service_email}** as an editor.\n\n"
            f"Details: {type(e).__name__}: {e}")
        st.stop()

# --------------------------------------------------------------------------
# Sidebar: data sources
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Data")
    if store.kind == "sheets":
        st.caption("Your data is saved in Google Sheets. Upload new Collectr exports here, "
                   "then save them so they stay.")
    else:
        st.caption("Upload new Collectr exports here, or put them in the app's data folder "
                   "so they load automatically.")
    inv_upload = st.file_uploader("Inventory export", type=["csv"], key="inv_up")
    sales_uploads = st.file_uploader("Transaction log exports (one file per show)", type=["csv"],
                                     accept_multiple_files=True, key="sales_up")
    st.caption("Each transaction log file becomes a show, named after the file. "
               "You can rename shows on the Shows & expenses tab.")

    if (inv_upload or sales_uploads) and st.button(f"Save uploads to {store.where}",
                                                   width="stretch", type="primary"):
        with st.spinner(f"Saving to {store.where}…"):
            if inv_upload:
                store.save_inventory(inv_upload.getvalue())
            for f in sales_uploads or []:
                store.save_sales(show_name_from_file(f.name), f.getvalue(), f.name)
        st.success(f"Saved to {store.where}. These files will load automatically next time.")

    if store.kind == "sheets":
        if st.button("Reload from Google Sheets", width="stretch",
                     help="Use this after editing the Google Sheet directly."):
            store.refresh()
            st.rerun()
        st.link_button("Open the Google Sheet", store.link, width="stretch")

# Inventory: an upload wins, otherwise what's stored
inv_bytes, inv_source = store.inventory()
if inv_upload is not None:
    inv_bytes, inv_source = inv_upload.getvalue(), inv_upload.name

# Sales: everything stored, plus uploads (an upload with the same show name wins)
sales_files: dict[str, tuple[str, bytes]] = store.sales()
stored_shows = sorted(sales_files)
for f in sales_uploads or []:
    sales_files[show_name_from_file(f.name)] = (f.name, f.getvalue())

inv, inv_original, as_of = (None, None, "")
if inv_bytes:
    try:
        inv, inv_original, as_of = parse_inventory(inv_bytes)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the inventory ({inv_source}): {e}. "
                 "Check that it's a Collectr CSV export.")

sales_parts, sales_originals = [], {}
for show, (source, raw) in sales_files.items():
    try:
        part, orig = parse_sales(raw, show)
        sales_parts.append(part)
        sales_originals[show] = (source, orig, raw)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the sales for {show} ({source}): {e}.")
sales = pd.concat(sales_parts, ignore_index=True) if sales_parts else None

if inv is None and sales is None:
    st.markdown("## Card Show Analytics")
    if store.kind == "sheets":
        st.markdown(
            "Your Google Sheet is connected but empty. Upload your Collectr **inventory** "
            "export and a **transaction log** export for each show in the sidebar, then "
            "click **Save uploads to Google Sheets**.")
    else:
        st.markdown(
            "Add your Collectr exports to get started: your **inventory** export and a "
            "**transaction log** export for each show. Use the uploaders in the sidebar, or "
            "copy the files into the app's `data` folder (`data/inventory.csv` and `data/sales/`).")
    st.stop()

# Map portfolio -> game so sales (which have no game column) can be filtered by game
portfolio_game: dict[str, str] = {}
if inv is not None:
    portfolio_game = inv.groupby("Portfolio")["Game"].agg(lambda s: s.mode().iat[0]).to_dict()
if sales is not None:
    sales["Game"] = sales["Portfolio"].map(portfolio_game).fillna(
        sales["Portfolio"].str.split().str[0].fillna("Other"))

expenses_all = store.expenses()
expenses_all["Amount"] = to_num(expenses_all["Amount"]).fillna(0.0)

# --------------------------------------------------------------------------
# Sidebar: filters
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.markdown("### Filters")
    all_shows = sorted(sales["Show"].unique()) if sales is not None else []
    if st.session_state.pop("_reset_show_filter", False):
        st.session_state.pop("shows", None)
    sel_shows = st.multiselect("Card show", all_shows, default=all_shows, key="shows",
                               help="Applies to sales and show expenses.")

    games = sorted(set(inv["Game"].unique() if inv is not None else [])
                   | set(sales["Game"].unique() if sales is not None else []))
    sel_games = st.multiselect("Game", games, default=games)

    portfolios = sorted(set(inv["Portfolio"].unique() if inv is not None else [])
                        | set(sales["Portfolio"].unique() if sales is not None else []))
    hide_pc = st.checkbox("Hide personal collection", value=False, key="hide_pc",
                          help="Hides portfolios with 'PC' in the name, so only "
                               "for-sale stock counts.")
    port_options = [p for p in portfolios if not (hide_pc and re.search(r"\bPC\b", p))]
    sel_ports = st.multiselect("Portfolio", port_options, default=port_options)

    outcome = st.radio("Results", ["All", "Gains only", "Losses only"], horizontal=True, key="outcome",
                       help="Filters cards by whether they made or lost money. "
                            "Applies to both realized and unrealized numbers.")
    exclude_zero = st.checkbox(
        "Leave out $0-cost cards", value=False, key="exclude_zero",
        help="Cards with no cost entered count their full market value as gain. "
             "Turn this on to judge only cards you know the cost of.")
    st.caption("Market values use Collectr's price, or your price override when you set one."
               + (f" Prices as of {as_of}." if as_of else ""))


def apply_outcome(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if outcome == "Gains only":
        return df[df[col] > 0]
    if outcome == "Losses only":
        return df[df[col] < 0]
    return df


# Filtered frames
inv_f = None
if inv is not None:
    inv_f = inv[inv["Game"].isin(sel_games) & inv["Portfolio"].isin(sel_ports)]
    if exclude_zero:
        inv_f = inv_f[~inv_f["Zero cost"]]
    inv_f = apply_outcome(inv_f, "Unrealized")
    inv_valued = inv_f[inv_f["Has value"]]

sales_f = None
if sales is not None:
    sales_f = sales[sales["Show"].isin(sel_shows) & sales["Game"].isin(sel_games)
                    & sales["Portfolio"].isin(sel_ports)]
    if exclude_zero:
        sales_f = sales_f[~sales_f["Zero cost"]]
    sales_f = apply_outcome(sales_f, "Realized")

exp_f = expenses_all[expenses_all["Show"].isin(sel_shows)] if len(expenses_all) else expenses_all

# --------------------------------------------------------------------------
# Headline numbers
# --------------------------------------------------------------------------
revenue = float(sales_f["Revenue"].sum()) if sales_f is not None else 0.0
sold_cost = float(sales_f["Cost"].sum()) if sales_f is not None else 0.0
realized = float(sales_f["Realized"].sum()) if sales_f is not None else 0.0
cards_sold = int(sales_f["Qty"].sum()) if sales_f is not None else 0
total_expenses = float(to_num(exp_f["Amount"]).fillna(0.0).sum()) if len(exp_f) else 0.0
net = realized - total_expenses

mkt_value = float(inv_valued["Market value"].sum()) if inv_f is not None else 0.0
cost_basis = float(inv_valued["Cost"].sum()) if inv_f is not None else 0.0
unrealized = mkt_value - cost_basis
cards_in_stock = int(inv_f["Qty"].sum()) if inv_f is not None else 0
missing_value = int(inv_f.loc[~inv_f["Has value"], "Qty"].sum()) if inv_f is not None else 0
missing_cost_paid = float(inv_f.loc[~inv_f["Has value"], "Cost"].sum()) if inv_f is not None else 0
zero_cost_cards = int(inv_f.loc[inv_f["Zero cost"], "Qty"].sum()) if inv_f is not None else 0

n_shows = len(sel_shows)
st.title("Card Show Analytics")

if sales_f is not None and n_shows:
    show_word = "show" if n_shows == 1 else "shows"
    sentence = (f"Across {n_shows} {show_word} you sold {cards_sold:,} cards for "
                f"{money(revenue)}, against {money(sold_cost)} you'd paid for them. ")
    if total_expenses:
        sentence += f"After {money(total_expenses)} in expenses, you kept {money(net)}. "
    else:
        sentence += "Add your table fee and other costs on the Shows & expenses tab to see true profit. "
    if inv_f is not None:
        sentence += (f"Your {cards_in_stock:,} cards in stock are worth {money(mkt_value)} "
                     f"at market, {money(unrealized, signed=True)} versus what you paid.")
    label = "Net profit from shows" if total_expenses else "Realized profit from shows"
    big = net if total_expenses else realized
else:
    sentence = (f"Your {cards_in_stock:,} cards in stock are worth {money(mkt_value)} at market, "
                f"against {money(cost_basis)} paid.")
    label, big = "Unrealized profit on inventory", unrealized

filter_bits = []
if outcome != "All":
    filter_bits.append(outcome.lower())
if exclude_zero:
    filter_bits.append("$0-cost cards left out")
if hide_pc:
    filter_bits.append("personal collection hidden")
note = f"Filtered: {', '.join(filter_bits)}." if filter_bits else ""

st.markdown(
    f"""
<div class="hero">
  <div class="hero-label">{label}</div>
  <div class="hero-number {tone(big)}">{money(big, signed=True)}</div>
  <div class="hero-sentence">{sentence}</div>
  {f'<div class="hero-note">{note}</div>' if note else ''}
</div>
""",
    unsafe_allow_html=True,
)


def stat(value: str, key: str, sub: str = "", sub_tone: str = "flat") -> str:
    sub_html = f'<div class="stat-sub {sub_tone}">{sub}</div>' if sub else ""
    return (f'<div class="stat"><div class="stat-value">{value}</div>'
            f'<div class="stat-key">{key}</div>{sub_html}</div>')


avg_margin = realized / revenue if revenue else np.nan
unreal_ret = unrealized / cost_basis if cost_basis else np.nan
stats_html = "".join([
    stat(money(mkt_value), "Market value of stock", f"{cards_in_stock:,} cards"),
    stat(money(cost_basis), "Paid for stock"),
    stat(money(unrealized, signed=True), "Unrealized P/L", pct(unreal_ret), tone(unrealized)),
    stat(money(realized, signed=True), "Realized P/L", f"{pct(avg_margin, signed=False)} margin"
         if revenue else "", tone(realized)),
    stat(money(revenue), "Sales revenue", f"{cards_sold:,} cards sold"),
    stat(money(total_expenses), "Show expenses"),
    stat(money(net, signed=True), "Net after expenses", "", tone(net)),
])
st.markdown(f'<div class="stats">{stats_html}</div>', unsafe_allow_html=True)

caveats = []
if missing_value:
    caveats.append(f"{missing_value} card{'s' if missing_value != 1 else ''} have no market price in "
                   f"Collectr and are left out of market value and unrealized P/L "
                   f"({money(missing_cost_paid)} paid). Set a price override in Collectr to include them.")
if zero_cost_cards and not exclude_zero:
    caveats.append(f"{zero_cost_cards} cards have a $0 cost, so their full market value counts as "
                   "unrealized gain.")
if caveats:
    with st.expander("About these numbers"):
        for c in caveats:
            st.markdown(f"- {c}")

# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
tab_over, tab_real, tab_unreal, tab_shows, tab_files = st.tabs(
    ["Overview", "Realized", "Unrealized", "Shows & expenses", "Files"])

gl_colors = {"Gain": GAIN, "Loss": LOSS, "Even": "#A3AABA"}


def gl(series: pd.Series) -> pd.Series:
    return np.where(series > 0, "Gain", np.where(series < 0, "Loss", "Even"))


# ---------------- Overview ----------------
with tab_over:
    c1, c2 = st.columns(2)
    with c1:
        if sales_f is not None and len(sales_f):
            by_show = sales_f.groupby("Show", as_index=False)[["Revenue", "Cost", "Realized"]].sum()
            by_show["Expenses"] = expenses_by_show(exp_f, by_show["Show"])
            by_show["Net"] = by_show["Realized"] - by_show["Expenses"]
            long = by_show.melt(id_vars="Show", value_vars=["Revenue", "Cost", "Expenses", "Net"],
                                var_name="Measure", value_name="Amount")
            fig = px.bar(long, x="Show", y="Amount", color="Measure", barmode="group",
                         title="Each show at a glance",
                         color_discrete_map={"Revenue": INDIGO, "Cost": "#9AA6EC",
                                             "Expenses": "#D9A441", "Net": GAIN})
            fig.update_traces(hovertemplate="%{x}<br>%{fullData.name}: $%{y:,.2f}<extra></extra>")
            fig.for_each_trace(lambda t: t.update(marker_color=[GAIN if v >= 0 else LOSS for v in t.y])
                               if t.name == "Net" else None)
            fig.update_yaxes(tickprefix="$", title=None)
            fig.update_xaxes(title=None)
            show_chart(style_fig(fig))
        else:
            empty("No sales match the current filters.")
    with c2:
        if inv_f is not None and len(inv_valued):
            by_port = inv_valued.groupby("Portfolio", as_index=False)["Market value"].sum()
            fig = px.pie(by_port, names="Portfolio", values="Market value", hole=0.62,
                         title="Where your inventory value sits",
                         color_discrete_sequence=SERIES)
            fig.update_traces(textinfo="percent", textposition="inside",
                              hovertemplate="%{label}<br>$%{value:,.0f} (%{percent})<extra></extra>",
                              sort=True)
            fig.add_annotation(text=f"<b>{money(mkt_value)}</b><br><span style='font-size:12px;color:{MUTED}'>market value</span>",
                               showarrow=False, font=dict(size=18, color=INK))
            show_chart(style_fig(fig, legend=True))
        else:
            empty("No inventory matches the current filters.")

    c3, c4 = st.columns(2)
    with c3:
        if inv_f is not None and len(inv_valued):
            bp = inv_valued.groupby("Portfolio", as_index=False)[["Cost", "Market value"]].sum()
            bp = bp.sort_values("Market value")
            fig = go.Figure()
            fig.add_bar(y=bp["Portfolio"], x=bp["Cost"], name="Paid", orientation="h",
                        marker_color="#B8C0EE",
                        hovertemplate="%{y}<br>Paid: $%{x:,.0f}<extra></extra>")
            fig.add_bar(y=bp["Portfolio"], x=bp["Market value"], name="Market value", orientation="h",
                        marker_color=INDIGO,
                        hovertemplate="%{y}<br>Market: $%{x:,.0f}<extra></extra>")
            fig.update_layout(barmode="group", title="Paid vs market value, by portfolio")
            fig.update_xaxes(tickprefix="$", showgrid=True, gridcolor=GRID)
            show_chart(style_fig(fig))
    with c4:
        if inv_f is not None and len(inv_valued):
            top = inv_valued.sort_values("Market value", ascending=False)
            top10 = top.head(10)
            share = top10["Market value"].sum() / mkt_value if mkt_value else 0
            fig = px.bar(top10.iloc[::-1], x="Market value", y="Label", orientation="h",
                         title=f"Top 10 cards hold {share:.0%} of your value",
                         color_discrete_sequence=[INDIGO])
            fig.update_traces(hovertemplate="%{y}<br>$%{x:,.0f}<extra></extra>")
            fig.update_xaxes(tickprefix="$", title=None, showgrid=True, gridcolor=GRID)
            fig.update_yaxes(title=None, showgrid=False)
            show_chart(style_fig(fig, legend=False))

# ---------------- Realized ----------------
with tab_real:
    if sales_f is None or not len(sales_f):
        empty("No sales match the current filters. Add a sold export in the sidebar, "
              "or widen the filters.")
    else:
        wins = sales_f[sales_f["Realized"] > 0]
        losses = sales_f[sales_f["Realized"] < 0]
        best = sales_f.loc[sales_f["Realized"].idxmax()]
        worst = sales_f.loc[sales_f["Realized"].idxmin()]
        mean_days = sales_f["Days held"].mean()
        st.markdown(
            '<div class="stats">' + "".join([
                stat(money(wins["Realized"].sum(), signed=True), "Realized gains",
                     f"{len(wins)} sales", "gain"),
                stat(money(losses["Realized"].sum(), signed=True), "Realized losses",
                     f"{len(losses)} sales", "loss" if len(losses) else "flat"),
                stat(f"{len(wins) / len(sales_f):.0%}", "Sales at a profit"),
                stat(money(revenue / cards_sold if cards_sold else 0), "Average sale"),
                stat(money(best["Realized"], signed=True), "Best sale", best["Card"]),
                stat(money(worst["Realized"], signed=True), "Worst sale", worst["Card"]),
                stat(f"{mean_days:,.0f} days" if not np.isnan(mean_days) else "–",
                     "Average time held"),
            ]) + "</div>", unsafe_allow_html=True)

        c1, c2 = st.columns([3, 2])
        with c1:
            d = sales_f.sort_values("Realized").copy()
            d["Result"] = gl(d["Realized"])
            fig = px.bar(d, x="Realized", y="Label", orientation="h", color="Result",
                         color_discrete_map=gl_colors, title="Profit on every card sold",
                         custom_data=["Show", "Unit cost", "Unit price"])
            fig.update_traces(hovertemplate="%{y}<br>Profit: $%{x:,.2f}<br>Paid $%{customdata[1]:,.2f}, "
                                            "sold $%{customdata[2]:,.2f}<br>%{customdata[0]}<extra></extra>")
            fig.update_xaxes(tickprefix="$", title=None, showgrid=True, gridcolor=GRID)
            fig.update_yaxes(title=None, showgrid=False)
            show_chart(style_fig(fig, height=max(360, 22 * len(d) + 80), legend=False))
        with c2:
            daily = (sales_f.dropna(subset=["Sold"]).groupby(sales_f["Sold"].dt.date)
                     .agg(Realized=("Realized", "sum"), Revenue=("Revenue", "sum")).reset_index())
            daily = daily.rename(columns={"Sold": "Date"}).sort_values("Date")
            daily["Cumulative profit"] = daily["Realized"].cumsum()
            daily["Cumulative revenue"] = daily["Revenue"].cumsum()
            fig = go.Figure()
            fig.add_scatter(x=daily["Date"], y=daily["Cumulative revenue"], name="Revenue",
                            mode="lines+markers", line=dict(color="#9AA6EC", width=2),
                            hovertemplate="%{x}<br>Revenue to date: $%{y:,.0f}<extra></extra>")
            fig.add_scatter(x=daily["Date"], y=daily["Cumulative profit"], name="Profit",
                            mode="lines+markers", line=dict(color=GAIN, width=3),
                            hovertemplate="%{x}<br>Profit to date: $%{y:,.0f}<extra></extra>")
            fig.update_layout(title="Running totals by sale date")
            fig.update_yaxes(tickprefix="$")
            fig.update_xaxes(type="category" if len(daily) < 4 else "date")
            show_chart(style_fig(fig))

            by_type = sales_f.groupby("Type", as_index=False)[["Revenue", "Realized"]].sum()
            fig = px.pie(by_type, names="Type", values="Revenue", hole=0.55,
                         title="Revenue: raw vs graded",
                         color="Type", color_discrete_map={"Raw": "#9AA6EC", "Graded": INDIGO})
            fig.update_traces(textinfo="label+percent",
                              customdata=by_type[["Realized"]].values,
                              hovertemplate="%{label}<br>Revenue $%{value:,.0f}<br>"
                                            "Profit $%{customdata[0]:,.0f}<extra></extra>")
            show_chart(style_fig(fig, height=300, legend=False))

        c3, c4 = st.columns(2)
        with c3:
            d = sales_f.dropna(subset=["Days held"]).copy()
            if len(d):
                d["Result"] = gl(d["Realized"])
                fig = px.scatter(d, x="Days held", y="Realized", size="Revenue", color="Result",
                                 color_discrete_map=gl_colors, hover_name="Label", size_max=38,
                                 title="Does holding longer pay off?")
                fig.update_traces(hovertemplate="%{hovertext}<br>Held %{x} days<br>"
                                                "Profit $%{y:,.2f}<extra></extra>")
                fig.update_yaxes(tickprefix="$", title="Profit")
                show_chart(style_fig(fig, legend=False))
        with c4:
            g = sales_f.groupby("Grade group", as_index=False).agg(
                Revenue=("Revenue", "sum"), Realized=("Realized", "sum"), Cards=("Qty", "sum"))
            g["Margin"] = np.where(g["Revenue"] > 0, g["Realized"] / g["Revenue"], 0)
            g = g.sort_values("Realized")
            fig = px.bar(g, x="Grade group", y="Realized", title="Profit by grade",
                         color=gl(g["Realized"]), color_discrete_map=gl_colors,
                         custom_data=["Cards", "Margin"])
            fig.update_traces(hovertemplate="%{x}<br>Profit $%{y:,.0f}<br>%{customdata[0]} cards, "
                                            "%{customdata[1]:.0%} margin<extra></extra>")
            fig.update_yaxes(tickprefix="$", title=None)
            fig.update_xaxes(title=None)
            show_chart(style_fig(fig, legend=False))

        st.subheader("Sales")
        st.dataframe(
            sales_f[["Show", "Sold", "Card", "Portfolio", "Grade", "Qty", "Unit cost",
                     "Unit price", "Realized", "Margin", "Days held"]]
            .sort_values("Realized", ascending=False),
            hide_index=True, width="stretch",
            column_config={
                "Sold": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Unit cost": st.column_config.NumberColumn("Paid", format="$%.2f"),
                "Unit price": st.column_config.NumberColumn("Sold for", format="$%.2f"),
                "Realized": st.column_config.NumberColumn("Profit", format="$%.2f"),
                "Margin": st.column_config.NumberColumn(format="percent"),
            })

# ---------------- Unrealized ----------------
with tab_unreal:
    if inv_f is None or not len(inv_valued):
        empty("No inventory matches the current filters. Add your inventory export in the sidebar.")
    else:
        gainers = inv_valued[inv_valued["Unrealized"] > 0]
        losers = inv_valued[inv_valued["Unrealized"] < 0]
        st.markdown(
            '<div class="stats">' + "".join([
                stat(money(gainers["Unrealized"].sum(), signed=True), "Unrealized gains",
                     f"{int(gainers['Qty'].sum())} cards", "gain"),
                stat(money(losers["Unrealized"].sum(), signed=True), "Unrealized losses",
                     f"{int(losers['Qty'].sum())} cards", "loss" if len(losers) else "flat"),
                stat(pct(unreal_ret), "Return on what you paid", "", tone(unrealized)),
                stat(money(mkt_value / cards_in_stock if cards_in_stock else 0), "Average card value"),
                stat(f"{int(inv_valued.loc[inv_valued['Unit value'] >= 100, 'Qty'].sum()):,}",
                     "Cards worth $100+"),
            ]) + "</div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        n_top = 12
        with c1:
            d = gainers.sort_values("Unrealized", ascending=False).head(n_top).iloc[::-1]
            if len(d):
                fig = px.bar(d, x="Unrealized", y="Label", orientation="h",
                             title="Biggest unrealized gains", color_discrete_sequence=[GAIN],
                             custom_data=["Cost", "Market value"])
                fig.update_traces(hovertemplate="%{y}<br>+$%{x:,.2f}<br>Paid $%{customdata[0]:,.2f}, "
                                                "worth $%{customdata[1]:,.2f}<extra></extra>")
                fig.update_xaxes(tickprefix="$", title=None, showgrid=True, gridcolor=GRID)
                fig.update_yaxes(title=None)
                show_chart(style_fig(fig, height=420, legend=False))
            else:
                empty("No cards are up right now.")
        with c2:
            d = losers.sort_values("Unrealized").head(n_top).iloc[::-1]
            if len(d):
                fig = px.bar(d, x="Unrealized", y="Label", orientation="h",
                             title="Biggest unrealized losses", color_discrete_sequence=[LOSS],
                             custom_data=["Cost", "Market value"])
                fig.update_traces(hovertemplate="%{y}<br>$%{x:,.2f}<br>Paid $%{customdata[0]:,.2f}, "
                                                "worth $%{customdata[1]:,.2f}<extra></extra>")
                fig.update_xaxes(tickprefix="$", title=None, showgrid=True, gridcolor=GRID)
                fig.update_yaxes(title=None)
                show_chart(style_fig(fig, height=420, legend=False))
            else:
                empty("No cards are down right now.")

        c3, c4 = st.columns(2)
        with c3:
            split_by = st.radio("Break down value by", ["Game", "Type", "Grade group", "Condition"],
                                horizontal=True, key="split_by")
            d = inv_valued.groupby(split_by, as_index=False)["Market value"].sum()
            if split_by == "Grade group":
                d = d.sort_values("Market value", ascending=False)
                if len(d) > 8:
                    other = d.iloc[7:]["Market value"].sum()
                    d = pd.concat([d.head(7), pd.DataFrame({split_by: ["Other"], "Market value": [other]})])
            fig = px.pie(d, names=split_by, values="Market value", hole=0.55,
                         title=f"Market value by {split_by.lower()}", color_discrete_sequence=SERIES)
            fig.update_traces(textinfo="percent", textposition="inside",
                              hovertemplate="%{label}<br>$%{value:,.0f} (%{percent})<extra></extra>")
            show_chart(style_fig(fig))
        with c4:
            t = inv_f.dropna(subset=["Date added"]).sort_values("Date added")
            t = t.groupby(t["Date added"].dt.date).agg(Cost=("Cost", "sum"),
                                                       Value=("Market value", "sum")).reset_index()
            t["Paid (cumulative)"] = t["Cost"].cumsum()
            t["Market value today (cumulative)"] = t["Value"].cumsum()
            fig = go.Figure()
            fig.add_scatter(x=t["Date added"], y=t["Paid (cumulative)"], name="Paid",
                            line=dict(color="#9AA6EC", width=2, shape="hv"),
                            hovertemplate="%{x}<br>Paid to date: $%{y:,.0f}<extra></extra>")
            fig.add_scatter(x=t["Date added"], y=t["Market value today (cumulative)"],
                            name="Worth today", line=dict(color=INDIGO, width=3, shape="hv"),
                            fill="tonexty", fillcolor="rgba(51,68,158,0.08)",
                            hovertemplate="%{x}<br>Worth today: $%{y:,.0f}<extra></extra>")
            fig.update_layout(title="Current stock by date added: paid vs worth today")
            fig.update_yaxes(tickprefix="$")
            show_chart(style_fig(fig, height=400))

        by_set = inv_valued.groupby("Set", as_index=False).agg(
            Unrealized=("Unrealized", "sum"), Value=("Market value", "sum"))
        by_set = by_set.reindex(by_set["Unrealized"].abs().sort_values(ascending=False).index).head(15)
        by_set = by_set.sort_values("Unrealized")
        fig = px.bar(by_set, x="Unrealized", y="Set", orientation="h",
                     color=gl(by_set["Unrealized"]), color_discrete_map=gl_colors,
                     title="Sets moving your unrealized P/L the most", custom_data=["Value"])
        fig.update_traces(hovertemplate="%{y}<br>Unrealized $%{x:,.0f}<br>Worth $%{customdata[0]:,.0f}"
                                        "<extra></extra>")
        fig.update_xaxes(tickprefix="$", title=None, showgrid=True, gridcolor=GRID)
        fig.update_yaxes(title=None)
        show_chart(style_fig(fig, height=460, legend=False))

        st.subheader("Inventory")
        q = st.text_input("Search cards", placeholder="Card, set or grade", key="inv_search")
        tbl = inv_f.copy()
        if q:
            mask = (tbl["Card"].str.contains(q, case=False, na=False)
                    | tbl["Set"].str.contains(q, case=False, na=False)
                    | tbl["Grade"].str.contains(q, case=False, na=False))
            tbl = tbl[mask]
        st.dataframe(
            tbl[["Card", "Set", "Portfolio", "Grade", "Condition", "Qty", "Unit cost",
                 "Unit value", "Cost", "Market value", "Unrealized", "Return", "Date added"]]
            .sort_values("Market value", ascending=False),
            hide_index=True, width="stretch",
            column_config={
                "Unit cost": st.column_config.NumberColumn("Paid each", format="$%.2f"),
                "Unit value": st.column_config.NumberColumn("Worth each", format="$%.2f"),
                "Cost": st.column_config.NumberColumn("Paid total", format="$%.2f"),
                "Market value": st.column_config.NumberColumn("Worth total", format="$%.2f"),
                "Unrealized": st.column_config.NumberColumn(format="$%.2f"),
                "Return": st.column_config.NumberColumn(format="percent"),
                "Date added": st.column_config.DateColumn(format="YYYY-MM-DD"),
            })

# ---------------- Shows & expenses ----------------
with tab_shows:
    if sales is None:
        empty("Add a sold export for a show to track it here.")
    else:
        all_sales_sel = sales[sales["Show"].isin(sel_shows)]
        summary = all_sales_sel.groupby("Show").agg(
            First_sale=("Sold", "min"), Last_sale=("Sold", "max"), Cards=("Qty", "sum"),
            Revenue=("Revenue", "sum"), Cost=("Cost", "sum"), Realized=("Realized", "sum"),
        ).reset_index()
        summary["Expenses"] = expenses_by_show(expenses_all, summary["Show"])
        summary["Net"] = summary["Realized"] - summary["Expenses"]
        summary["Margin"] = np.where(summary["Revenue"] > 0, summary["Net"] / summary["Revenue"], np.nan)
        st.subheader("Show results")
        with st.expander("Rename a show"):
            r1, r2, r3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            old_name = r1.selectbox("Show", stored_shows, key="rename_from")
            new_name = r2.text_input("New name", key="rename_to",
                                     placeholder="e.g. Bossa Nova Card Show – Oct 2026")
            if r3.button("Rename", width="stretch", key="rename_btn"):
                new_clean = (new_name or "").strip()
                taken = set(sales_files) - {old_name}
                if not old_name:
                    st.error("Save a show first, then you can rename it.")
                elif not new_clean:
                    st.error("Type a new name first.")
                elif new_clean in taken:
                    st.error(f"There's already a show called {new_clean}. Pick a different name.")
                elif new_clean != old_name:
                    store.rename_show(old_name, new_clean)
                    st.session_state["_reset_show_filter"] = True
                    st.session_state.pop("rename_to", None)
                    st.toast(f"Renamed to {new_clean}")
                    st.rerun()
            st.caption("Renames the show everywhere in the dashboard and moves its expenses "
                       "with it." + (" The show's tab in Google Sheets is renamed too."
                                     if store.kind == "sheets" else
                                     " Your exported file keeps its original name."))
        st.markdown('<p class="section-note">Every sale in each file, ignoring the game, portfolio and '
                    'result filters, so each show is shown in full.</p>', unsafe_allow_html=True)
        st.dataframe(
            summary, hide_index=True, width="stretch",
            column_config={
                "First_sale": st.column_config.DateColumn("First sale", format="YYYY-MM-DD"),
                "Last_sale": st.column_config.DateColumn("Last sale", format="YYYY-MM-DD"),
                "Revenue": st.column_config.NumberColumn(format="$%.2f"),
                "Cost": st.column_config.NumberColumn("Paid", format="$%.2f"),
                "Realized": st.column_config.NumberColumn("Realized profit", format="$%.2f"),
                "Expenses": st.column_config.NumberColumn(format="$%.2f"),
                "Net": st.column_config.NumberColumn("Net profit", format="$%.2f"),
                "Margin": st.column_config.NumberColumn("Net margin", format="percent"),
            })

        st.subheader("Expenses")
        st.markdown('<p class="section-note">Collectr doesn\'t export costs, so log them here: '
                    'table fees, travel, food, supplies. Add a row per expense, then save.</p>',
                    unsafe_allow_html=True)
        c1, c2 = st.columns([3, 2])
        with c1:
            edited = st.data_editor(
                expenses_all, num_rows="dynamic", hide_index=True, width="stretch",
                key="expense_editor",
                column_config={
                    "Show": st.column_config.SelectboxColumn(options=all_shows, required=True),
                    "Category": st.column_config.SelectboxColumn(options=EXPENSE_CATEGORIES,
                                                                 required=True),
                    "Amount": st.column_config.NumberColumn(format="$%.2f", min_value=0.0,
                                                            required=True),
                    "Note": st.column_config.TextColumn(),
                })
            b1, b2 = st.columns(2)
            if b1.button("Save expenses", type="primary", width="stretch"):
                with st.spinner(f"Saving to {store.where}…"):
                    store.save_expenses(edited.dropna(subset=["Show"]))
                st.toast("Expenses saved")
                st.rerun()
            b2.download_button("Download expenses", expenses_all.to_csv(index=False),
                               "expenses.csv", "text/csv", width="stretch")
        with c2:
            if len(exp_f) and exp_f["Amount"].sum() > 0:
                d = exp_f.groupby("Category", as_index=False)["Amount"].sum()
                fig = px.pie(d, names="Category", values="Amount", hole=0.55,
                             title="Where the money went", color_discrete_sequence=SERIES)
                fig.update_traces(textinfo="label+percent",
                                  hovertemplate="%{label}<br>$%{value:,.2f}<extra></extra>")
                show_chart(style_fig(fig, height=320, legend=False))
            else:
                empty("No saved expenses for the selected shows yet.")

# ---------------- Files ----------------
with tab_files:
    st.markdown(f'<p class="section-note">Your Collectr exports as stored in the {store.where}.</p>',
                unsafe_allow_html=True)
    if store.link:
        st.link_button("Open the Google Sheet", store.link)

    st.subheader("Inventory")
    if inv_original is not None:
        st.caption(f"{inv_source}: {len(inv_original):,} rows"
                   + (f", prices as of {as_of}" if as_of else ""))
        st.dataframe(inv_original, hide_index=True, width="stretch", height=380)
        st.download_button("Download inventory CSV", inv_bytes, "inventory.csv", "text/csv")
    else:
        empty("No inventory file loaded.")

    st.subheader("Sold files")
    if sales_originals:
        for show, (source, orig, raw) in sales_originals.items():
            with st.expander(f"{show}: {len(orig):,} sales", expanded=len(sales_originals) == 1):
                st.caption(f"Source: {source}")
                st.dataframe(orig, hide_index=True, width="stretch")
                st.download_button(f"Download {show}.csv", raw, f"{show}.csv",
                                   "text/csv", key=f"dl_{show}")
    else:
        empty("No sold files loaded.")
