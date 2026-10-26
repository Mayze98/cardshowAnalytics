"""
Card Show Ledger: a dashboard for Collectr exports.

Reads one Collectr inventory export plus any number of Collectr "sold" exports
(one per card show) and shows realized and unrealized profit, expenses, and
analytics.

Run:  streamlit run app.py
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------
# Paths and settings
# --------------------------------------------------------------------------
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR
INVENTORY_FILE = DATA_DIR / "inventory.csv"
SALES_DIR = DATA_DIR / "sales"
EXPENSES_FILE = DATA_DIR / "expenses.csv"
SHOWS_FILE = DATA_DIR / "shows.csv"
UNASSIGNED = "Non-show sales"

# Optional links to the original files (e.g. Google Sheets). Shown on the Files tab.
SOURCE_LINKS = {
    "Collectr inventory (Google Sheets)": "https://docs.google.com/spreadsheets/d/1w7yOrWuAotUUqF8gteVYApwq3oawyTNB2T0pSgycdHM",
    "Bossa show (Google Sheets)": "https://docs.google.com/spreadsheets/d/1WjpuIog_wMjYGonfBZ7qMsLImcZ5enZRI-ejrs1ybRw",
}

EXPENSE_CATEGORIES = ["Table fee", "Gas / travel", "Hotel", "Food", "Parking",
                      "Supplies", "Payment fees", "Grading", "Staffing fees", "Other"]

# Palette
INK = "#1C2430"
MUTED = "#6B7486"
GRID = "#E6E9EF"
GAIN = "#1F8A70"
LOSS = "#C8424F"
INDIGO = "#33449E"
SERIES = ["#33449E", "#5C6FD6", "#9AA6EC", "#1F8A70", "#7CC2AE",
          "#D9A441", "#C8424F", "#A3AABA", "#2C7DA0", "#B36A8F"]

st.set_page_config(page_title="Card Show Ledger", page_icon="🃏", layout="wide")

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
    return pd.to_numeric(cleaned.replace({"": np.nan, "nan": np.nan}), errors="coerce")


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
def parse_sales(raw: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    original = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                           engine="python", index_col=False)
    original.columns = [c.strip() for c in original.columns]
    cols = {c.lower(): c for c in original.columns}

    def col(name: str, default: str = "") -> pd.Series:
        key = cols.get(name.lower())
        return original[key] if key else pd.Series([default] * len(original))

    df = pd.DataFrame({
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


def load_shows() -> pd.DataFrame:
    if SHOWS_FILE.exists():
        df = pd.read_csv(SHOWS_FILE)
    else:
        df = pd.DataFrame(columns=["Name", "Start", "End"])
    for c in ["Name", "Start", "End"]:
        if c not in df:
            df[c] = None
    df["Name"] = df["Name"].astype(str).str.strip()
    df["Start"] = pd.to_datetime(df["Start"], errors="coerce").dt.date
    df["End"] = pd.to_datetime(df["End"], errors="coerce").dt.date
    return df[["Name", "Start", "End"]]


def assign_show(dates: pd.Series, shows_df: pd.DataFrame) -> pd.Series:
    out = pd.Series([UNASSIGNED] * len(dates), index=dates.index, dtype=object)
    d = pd.to_datetime(dates, errors="coerce").dt.date
    for _, row in shows_df.iterrows():
        name = str(row["Name"]).strip()
        start, end = row["Start"], row["End"]
        if not name or name.lower() == "nan" or pd.isna(start) or pd.isna(end):
            continue
        mask = d.notna() & (d >= start) & (d <= end)
        out = out.where(~mask, name)
    return out


def load_expenses() -> pd.DataFrame:
    if EXPENSES_FILE.exists():
        df = pd.read_csv(EXPENSES_FILE, dtype={"Show": str, "Category": str, "Note": str})
    else:
        df = pd.DataFrame(columns=["Show", "Category", "Amount", "Note"])
    for c in ["Show", "Category", "Note"]:
        if c not in df:
            df[c] = ""
    df["Amount"] = to_num(df.get("Amount", pd.Series(dtype=str))).fillna(0)
    return df[["Show", "Category", "Amount", "Note"]]


# --------------------------------------------------------------------------
# Sidebar: data sources
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Data")
    st.caption("Drop new Collectr exports here, or put them in the app's data folder "
               "so they load automatically.")
    inv_upload = st.file_uploader("Inventory export", type=["csv"], key="inv_up")
    sales_uploads = st.file_uploader("Sold exports", type=["csv"],
                                     accept_multiple_files=True, key="sales_up")
    st.caption("Upload any number of sold exports; rows are combined into one dataset. "
               "Define shows by date range in the *Shows & expenses* tab — rows get "
               "assigned to a show based on their date.")

    if (inv_upload or sales_uploads) and st.button("Save uploads to data folder",
                                                   width="stretch"):
        DATA_DIR.mkdir(exist_ok=True)
        SALES_DIR.mkdir(exist_ok=True)
        if inv_upload:
            INVENTORY_FILE.write_bytes(inv_upload.getvalue())
        for f in sales_uploads or []:
            (SALES_DIR / Path(f.name).name).write_bytes(f.getvalue())
        st.success("Saved. These files will load automatically next time.")

# Inventory: upload wins, else data folder
inv_bytes, inv_source = None, None
if inv_upload is not None:
    inv_bytes, inv_source = inv_upload.getvalue(), inv_upload.name
elif INVENTORY_FILE.exists():
    inv_bytes, inv_source = INVENTORY_FILE.read_bytes(), INVENTORY_FILE.name
else:
    # fall back to any csv in data/ that looks like an inventory export
    for p in sorted(DATA_DIR.glob("*.csv")) if DATA_DIR.exists() else []:
        if p.name != EXPENSES_FILE.name:
            head = p.read_text(errors="ignore").split("\n", 1)[0]
            if "Market Price" in head:
                inv_bytes, inv_source = p.read_bytes(), p.name
                break

# Sales: uploads plus everything in data/sales (an upload with the same filename wins)
sales_files: dict[str, bytes] = {}
if SALES_DIR.exists():
    for p in sorted(SALES_DIR.glob("*.csv")):
        sales_files[p.name] = p.read_bytes()
for f in sales_uploads or []:
    sales_files[Path(f.name).name] = f.getvalue()

inv, inv_original, as_of = (None, None, "")
if inv_bytes:
    try:
        inv, inv_original, as_of = parse_inventory(inv_bytes)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the inventory file ({inv_source}): {e}. "
                 "Check that it's a Collectr CSV export.")

sales_parts, sales_originals = [], {}
for fname, raw in sales_files.items():
    try:
        part, orig = parse_sales(raw)
        sales_parts.append(part)
        sales_originals[fname] = orig
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the sold file {fname}: {e}.")
sales = pd.concat(sales_parts, ignore_index=True) if sales_parts else None

shows_df = load_shows()
if sales is not None:
    sales["Show"] = assign_show(sales["Sold"], shows_df)
if inv is not None:
    inv["Show"] = assign_show(inv["Date added"], shows_df)

if inv is None and sales is None:
    st.markdown("## Card Show Ledger")
    st.markdown(
        "Add your Collectr exports to get started: your **inventory** export and a "
        "**sold** export for each show. Use the uploaders in the sidebar, or copy the "
        "files into the app's `data` folder (`data/inventory.csv` and `data/sales/`)."
    )
    st.stop()

# Map portfolio -> game so sales (which have no game column) can be filtered by game
portfolio_game: dict[str, str] = {}
if inv is not None:
    portfolio_game = inv.groupby("Portfolio")["Game"].agg(lambda s: s.mode().iat[0]).to_dict()
if sales is not None:
    sales["Game"] = sales["Portfolio"].map(portfolio_game).fillna(
        sales["Portfolio"].str.split().str[0].fillna("Other"))

expenses_all = load_expenses()

# --------------------------------------------------------------------------
# Sidebar: filters
# --------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.markdown("### Filters")
    show_set: set[str] = set(shows_df["Name"].dropna().astype(str).str.strip())
    show_set.discard("")
    if sales is not None:
        show_set |= set(sales["Show"].unique())
    if inv is not None:
        show_set |= set(inv["Show"].unique())
    all_shows = sorted(show_set - {UNASSIGNED}) + ([UNASSIGNED] if UNASSIGNED in show_set else [])
    sel_shows = st.multiselect("Card show", all_shows, default=all_shows, key="shows",
                               help="Applies to sales, inventory, and show expenses. "
                                    "'Non-show sales' = rows whose date falls outside every defined show.")

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
    inv_f = inv[inv["Game"].isin(sel_games) & inv["Portfolio"].isin(sel_ports)
                & inv["Show"].isin(sel_shows)]
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
total_expenses = float(exp_f["Amount"].sum()) if len(exp_f) else 0.0
net = realized - total_expenses

mkt_value = float(inv_valued["Market value"].sum()) if inv_f is not None else 0.0
cost_basis = float(inv_valued["Cost"].sum()) if inv_f is not None else 0.0
unrealized = mkt_value - cost_basis
cards_in_stock = int(inv_f["Qty"].sum()) if inv_f is not None else 0
missing_value = int(inv_f.loc[~inv_f["Has value"], "Qty"].sum()) if inv_f is not None else 0
missing_cost_paid = float(inv_f.loc[~inv_f["Has value"], "Cost"].sum()) if inv_f is not None else 0
zero_cost_cards = int(inv_f.loc[inv_f["Zero cost"], "Qty"].sum()) if inv_f is not None else 0

n_shows = len(sel_shows)
st.title("Card Show Ledger")

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
            exp_by_show = exp_f.groupby("Show")["Amount"].sum() if len(exp_f) else pd.Series(dtype=float)
            by_show["Expenses"] = by_show["Show"].map(exp_by_show).fillna(0)
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
    st.subheader("Define shows")
    st.markdown('<p class="section-note">Each show is a name plus a date range. '
                'Sales and inventory rows are assigned to a show based on their date '
                '(sold date for sales, date added for inventory). Rows outside every '
                'range are shown as *Non-show sales*.</p>', unsafe_allow_html=True)
    edited_shows = st.data_editor(
        shows_df, num_rows="dynamic", hide_index=True, width="stretch",
        key="shows_editor",
        column_config={
            "Name": st.column_config.TextColumn(required=True),
            "Start": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
            "End": st.column_config.DateColumn(format="YYYY-MM-DD", required=True),
        })
    if st.button("Save shows", type="primary"):
        DATA_DIR.mkdir(exist_ok=True)
        out = edited_shows.copy()
        out["Name"] = out["Name"].astype(str).str.strip()
        out = out[(out["Name"] != "") & out["Start"].notna() & out["End"].notna()]
        out.to_csv(SHOWS_FILE, index=False)
        st.toast(f"Saved {len(out)} show(s)")
        st.cache_data.clear()
        st.session_state.pop("shows_editor", None)
        st.rerun()

    st.divider()
    if sales is None:
        empty("Add a sold export to track show results here.")
    else:
        all_sales_sel = sales[sales["Show"].isin(sel_shows)]
        summary = all_sales_sel.groupby("Show").agg(
            First_sale=("Sold", "min"), Last_sale=("Sold", "max"), Cards=("Qty", "sum"),
            Revenue=("Revenue", "sum"), Cost=("Cost", "sum"), Realized=("Realized", "sum"),
        ).reset_index()
        exp_by_show = expenses_all.groupby("Show")["Amount"].sum()
        summary["Expenses"] = summary["Show"].map(exp_by_show).fillna(0)
        summary["Net"] = summary["Realized"] - summary["Expenses"]
        summary["Margin"] = np.where(summary["Revenue"] > 0, summary["Net"] / summary["Revenue"], np.nan)
        st.subheader("Show results")
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
                DATA_DIR.mkdir(exist_ok=True)
                out = edited.dropna(subset=["Show"]).copy()
                out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce").fillna(0)
                out.to_csv(EXPENSES_FILE, index=False)
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
    st.markdown('<p class="section-note">The files exactly as exported from Collectr.</p>',
                unsafe_allow_html=True)
    if SOURCE_LINKS:
        cols = st.columns(len(SOURCE_LINKS))
        for col_, (label_, url) in zip(cols, SOURCE_LINKS.items()):
            col_.link_button(f"Open {label_}", url, width="stretch")

    st.subheader("Inventory")
    if inv_original is not None:
        st.caption(f"{inv_source}: {len(inv_original):,} rows"
                   + (f", prices as of {as_of}" if as_of else ""))
        st.dataframe(inv_original, hide_index=True, width="stretch", height=380)
        st.download_button("Download inventory CSV", inv_bytes, inv_source or "inventory.csv",
                           "text/csv")
    else:
        empty("No inventory file loaded.")

    st.subheader("Sold files")
    if sales_originals:
        for fname, orig in sales_originals.items():
            with st.expander(f"{fname}: {len(orig):,} sales", expanded=len(sales_originals) == 1):
                st.dataframe(orig, hide_index=True, width="stretch")
                st.download_button(f"Download {fname}", sales_files[fname], fname,
                                   "text/csv", key=f"dl_{fname}")
    else:
        empty("No sold files loaded.")
