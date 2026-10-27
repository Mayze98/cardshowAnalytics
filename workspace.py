"""
The dashboard's data for one session, plus the save file that carries it between sessions.

Nothing is stored on the server. Everything lives in your browser session until you
download a save file, and comes back when you open that save file next time.

Save file (a .zip you keep on your computer):
    inventory.csv   your Collectr inventory export
    sales.csv       your full Collectr transaction log (all transactions)
    shows.csv       your shows: Show, Start date, End date
    expenses.csv    expenses you logged: Show, Category, Amount, Note

A sale belongs to a show when its sold date falls between the show's start and end
dates. Sales outside every show count as "Not at a show".
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import PurePosixPath

import pandas as pd
import streamlit as st

KEY = "workspace"
NOT_AT_SHOW = "Not at a show"
EXPENSE_COLS = ["Show", "Category", "Amount", "Note"]
SHOW_COLS = ["Show", "Start date", "End date"]


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
def _empty() -> dict:
    return {
        "inventory": None,        # (file name, bytes) or None
        "sales": None,            # (file name, bytes) or None
        "shows": empty_shows(),
        "expenses": empty_expenses(),
        "unsaved": False,
    }


def get() -> dict:
    if KEY not in st.session_state:
        st.session_state[KEY] = _empty()
    return st.session_state[KEY]


def is_empty(ws: dict) -> bool:
    return ws["inventory"] is None and ws["sales"] is None and not len(ws["shows"])


def mark_saved() -> None:
    get()["unsaved"] = False


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
def read_str_csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                       engine="python", index_col=False)


def empty_shows() -> pd.DataFrame:
    return pd.DataFrame({"Show": pd.Series(dtype=object),
                         "Start date": pd.Series(dtype=object),
                         "End date": pd.Series(dtype=object)})


def empty_expenses() -> pd.DataFrame:
    return pd.DataFrame({"Show": pd.Series(dtype=object), "Category": pd.Series(dtype=object),
                         "Amount": pd.Series(dtype="float64"), "Note": pd.Series(dtype=object)})


def _to_date(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "NaT", "None", "nan"):
        return None
    ts = pd.to_datetime(v, errors="coerce")
    return None if pd.isna(ts) else ts.date()


def clean_shows(df: pd.DataFrame) -> pd.DataFrame:
    """Tidy a shows table: trimmed names, real dates, end date defaults to start date."""
    rows = []
    for r in df.to_dict("records"):
        name = str(r.get("Show") or "").strip()
        if not name or name.lower() == "nan":
            continue
        start, end = _to_date(r.get("Start date")), _to_date(r.get("End date"))
        rows.append({"Show": name, "Start date": start, "End date": end or start})
    if not rows:
        return empty_shows()
    out = pd.DataFrame(rows, columns=SHOW_COLS).astype(object)
    return out.sort_values("Start date", key=lambda s: s.map(lambda d: d or date.max)) \
              .reset_index(drop=True)


def validate_shows(df: pd.DataFrame) -> list[str]:
    """Problems that stop a shows table from being used. Empty list means it's fine."""
    problems = []
    names = df["Show"].tolist()
    if NOT_AT_SHOW.lower() in [n.lower() for n in names]:
        problems.append(f"“{NOT_AT_SHOW}” is reserved for sales outside your shows. "
                        "Pick a different name.")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        problems.append("Each show needs its own name. Used more than once: " + ", ".join(dupes) + ".")
    for r in df.itertuples(index=False):
        if r[1] is None:
            problems.append(f"{r[0]} needs a start date.")
        elif r[2] < r[1]:
            problems.append(f"{r[0]} ends before it starts.")
        elif len(r[0]) > 90:
            problems.append(f"{r[0][:40]}… is too long. Keep names under 90 characters.")
    dated = [r for r in df.itertuples(index=False) if r[1] is not None and r[2] >= r[1]]
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            if a[1] <= b[2] and b[1] <= a[2]:
                problems.append(f"{a[0]} and {b[0]} overlap. A sale can only belong to one show.")
    return problems


def clean_expenses(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in EXPENSE_COLS:
        if c not in df:
            df[c] = ""
    amount = pd.to_numeric(df["Amount"].astype(str).str.replace(r"[,$\s]", "", regex=True),
                           errors="coerce")
    df["Amount"] = pd.array(amount).to_numpy(dtype="float64", na_value=float("nan"))
    df["Amount"] = df["Amount"].fillna(0.0)
    for c in ["Show", "Category", "Note"]:
        df[c] = df[c].fillna("").astype(str).replace({"nan": "", "None": ""}).astype(object)
    df = df[df["Show"].str.strip() != ""]
    return df[EXPENSE_COLS].reset_index(drop=True)


def looks_like_inventory(raw: bytes) -> bool:
    return "Market Price" in raw[:4000].decode("utf-8", errors="ignore").split("\n", 1)[0]


def looks_like_sales(raw: bytes) -> bool:
    return "Sold Price" in raw[:4000].decode("utf-8", errors="ignore").split("\n", 1)[0]


# --------------------------------------------------------------------------
# Changes
# --------------------------------------------------------------------------
def set_inventory(ws: dict, file_name: str, raw: bytes) -> None:
    ws["inventory"] = (file_name, raw)
    ws["unsaved"] = True


def set_sales(ws: dict, file_name: str, raw: bytes) -> None:
    ws["sales"] = (file_name, raw)
    ws["unsaved"] = True


def set_shows(ws: dict, new: pd.DataFrame, renames: dict[str, str]) -> None:
    """Replace the shows table. `renames` maps old names to new ones so expenses follow;
    expenses for shows that no longer exist are removed."""
    exp = ws["expenses"].copy()
    exp["Show"] = exp["Show"].map(lambda s: renames.get(s, s))
    exp = exp[exp["Show"].isin(set(new["Show"]))].reset_index(drop=True)
    ws["shows"] = new
    ws["expenses"] = exp
    ws["unsaved"] = True


def set_expenses(ws: dict, df: pd.DataFrame) -> None:
    ws["expenses"] = clean_expenses(df)
    ws["unsaved"] = True


# --------------------------------------------------------------------------
# Save file
# --------------------------------------------------------------------------
def _fmt(d) -> str:
    return d.isoformat() if isinstance(d, date) else ""


def to_save_file(ws: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if ws["inventory"] is not None:
            z.writestr("inventory.csv", ws["inventory"][1])
        if ws["sales"] is not None:
            z.writestr("sales.csv", ws["sales"][1])
        shows = ws["shows"].copy()
        shows["Start date"] = shows["Start date"].map(_fmt)
        shows["End date"] = shows["End date"].map(_fmt)
        z.writestr("shows.csv", shows[SHOW_COLS].to_csv(index=False))
        exp = ws["expenses"].copy()
        exp["Amount"] = exp["Amount"].map(lambda a: f"{float(a):.2f}")
        z.writestr("expenses.csv", exp[EXPENSE_COLS].to_csv(index=False))
    return buf.getvalue()


def from_save_file(raw: bytes) -> tuple[dict, list[str]]:
    """Read a save file. Returns (workspace, warnings)."""
    ws, warnings = _empty(), []
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValueError("That file isn't a save file. Save files are .zip files "
                         "downloaded from this dashboard.") from e

    files: dict[str, bytes] = {}
    for info in z.infolist():
        p = PurePosixPath(info.filename)
        if info.is_dir() or p.name.startswith(".") or "__MACOSX" in p.parts:
            continue
        files[info.filename] = z.read(info)

    def find(name: str) -> bytes | None:
        path = next((f for f in files if PurePosixPath(f).name.lower() == name
                     and "sales" not in [x.lower() for x in PurePosixPath(f).parts[:-1]]), None)
        return files[path] if path else None

    if (inv := find("inventory.csv")) is not None:
        ws["inventory"] = ("inventory.csv", inv)
    if (sales := find("sales.csv")) is not None:
        ws["sales"] = ("sales.csv", sales)
    if (shows := find("shows.csv")) is not None:
        shows_df = read_str_csv(shows)
        if "Sales file" in shows_df.columns:
            _upgrade_old_save_file(ws, files, shows_df, warnings)
        else:
            ws["shows"] = clean_shows(shows_df)
    if (exp := find("expenses.csv")) is not None:
        ws["expenses"] = clean_expenses(read_str_csv(exp))

    problems = validate_shows(ws["shows"]) if len(ws["shows"]) else []
    warnings.extend(f"Check your shows: {p}" for p in problems)
    if is_empty(ws):
        raise ValueError("That save file doesn't contain an inventory, sales or shows.")
    return ws, warnings


def _upgrade_old_save_file(ws: dict, files: dict[str, bytes], shows_df: pd.DataFrame,
                           warnings: list[str]) -> None:
    """Older save files kept one sales file per show. Combine them into one sales file and
    give each show the date range of its sales."""
    by_name = {PurePosixPath(f).name: b for f, b in files.items()
               if "sales" in [x.lower() for x in PurePosixPath(f).parts[:-1]]}
    parts, shows, expenses = [], [], []
    for r in shows_df.to_dict("records"):
        show, fname = str(r.get("Show", "")).strip(), str(r.get("Sales file", "")).strip()
        if not show:
            continue
        if str(r.get("Category", "")).strip() or str(r.get("Amount", "")).strip():
            expenses.append({"Show": show, "Category": r.get("Category", ""),
                             "Amount": r.get("Amount", ""), "Note": r.get("Note", "")})
        if show in [s["Show"] for s in shows]:
            continue
        start = end = None
        if fname in by_name:
            df = read_str_csv(by_name[fname])
            parts.append(df)
            sold = pd.to_datetime(df.get("Sold Date", pd.Series(dtype=str)), errors="coerce").dropna()
            if len(sold):
                start, end = sold.min().date(), sold.max().date()
        shows.append({"Show": show, "Start date": start, "End date": end})
    if parts and ws["sales"] is None:
        merged = pd.concat(parts, ignore_index=True).drop_duplicates()
        ws["sales"] = ("sales.csv", merged.to_csv(index=False).encode())
    ws["shows"] = clean_shows(pd.DataFrame(shows, columns=SHOW_COLS))
    if expenses:
        ws["expenses"] = clean_expenses(pd.DataFrame(expenses))
    warnings.append("This save file was made with an older version. Your shows were given the "
                    "dates of their sales. Check them on the Shows & expenses tab, then download "
                    "a new save file.")


def assign_shows(sold: pd.Series, shows: pd.DataFrame) -> pd.Series:
    """Show name for each sold date (NOT_AT_SHOW when it falls outside every show)."""
    out = pd.Series(NOT_AT_SHOW, index=sold.index, dtype=object)
    days = sold.dt.normalize()
    for r in shows.itertuples(index=False):
        if r[1] is None:
            continue
        mask = (days >= pd.Timestamp(r[1])) & (days <= pd.Timestamp(r[2] or r[1]))
        out[mask & (out == NOT_AT_SHOW)] = r[0]
    return out
