"""
The dashboard's data for one session, plus the save file that carries it between sessions.

Nothing is stored on the server. Everything lives in your browser session until you
download a save file, and comes back when you open that save file next time.

Save file (a .zip you keep on your computer):
    inventory.csv        your Collectr inventory export
    shows.csv            your shows and their expenses
    sales/<show>.csv     one Collectr transaction log per show
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePosixPath

import pandas as pd
import streamlit as st

EXPENSE_COLS = ["Show", "Category", "Amount", "Note"]
SALES_COLS = ["Portfolio Name", "Product Name", "Product Subtype", "Grade", "Quantity",
              "Purchase Price", "Purchase Date", "Purchase Note", "Card Condition",
              "Sold Price", "Sold Date", "Sold Note", "Profit"]
SHOWS_FILE_COLS = ["Show", "Sales file", "Category", "Amount", "Note"]

KEY = "workspace"


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
def _empty() -> dict:
    return {
        "inventory": None,            # (file name, bytes) or None
        "shows": {},                  # show name -> transaction log CSV bytes
        "expenses": empty_expenses(),
        "unsaved": False,
    }


def get() -> dict:
    if KEY not in st.session_state:
        st.session_state[KEY] = _empty()
    return st.session_state[KEY]


def is_empty(ws: dict) -> bool:
    return ws["inventory"] is None and not ws["shows"]


def mark_saved() -> None:
    get()["unsaved"] = False


# --------------------------------------------------------------------------
# CSV helpers
# --------------------------------------------------------------------------
def read_str_csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                       engine="python", index_col=False)


def empty_sales_csv() -> bytes:
    """A transaction log with headers but no sales, for a show added without a file."""
    return (",".join(SALES_COLS) + "\n").encode()


def empty_expenses() -> pd.DataFrame:
    return pd.DataFrame({"Show": pd.Series(dtype=object), "Category": pd.Series(dtype=object),
                         "Amount": pd.Series(dtype="float64"), "Note": pd.Series(dtype=object)})


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


def merge_sales(existing: bytes, new: bytes) -> tuple[bytes, int, int]:
    """Append new sales to existing ones, skipping exact duplicate rows.

    Returns (merged CSV, rows added, rows skipped).
    """
    old_df, new_df = read_str_csv(existing), read_str_csv(new)
    cols = list(old_df.columns) + [c for c in new_df.columns if c not in old_df.columns]
    old_df = old_df.reindex(columns=cols, fill_value="").astype(str)
    new_df = new_df.reindex(columns=cols, fill_value="").astype(str)
    seen = {tuple(r) for r in old_df.values.tolist()}
    keep = [tuple(r) not in seen for r in new_df.values.tolist()]
    merged = pd.concat([old_df, new_df[keep]], ignore_index=True)
    return merged.to_csv(index=False).encode(), int(sum(keep)), len(keep) - int(sum(keep))


def looks_like_inventory(raw: bytes) -> bool:
    return "Market Price" in raw[:4000].decode("utf-8", errors="ignore").split("\n", 1)[0]


def looks_like_sales(raw: bytes) -> bool:
    return "Sold Price" in raw[:4000].decode("utf-8", errors="ignore").split("\n", 1)[0]


def _file_stem(name: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .")
    return stem or "show"


# --------------------------------------------------------------------------
# Changes
# --------------------------------------------------------------------------
def set_inventory(ws: dict, file_name: str, raw: bytes) -> None:
    ws["inventory"] = (file_name, raw)
    ws["unsaved"] = True


def add_show(ws: dict, name: str, raw: bytes | None = None, append: bool = True) -> str:
    """Create a show, or add to / replace an existing show's sales. Returns a status message."""
    exists = name in ws["shows"]
    if raw is None:
        if not exists:
            ws["shows"][name] = empty_sales_csv()
            ws["unsaved"] = True
        return f"Added {name}"
    if exists and append:
        merged, added, skipped = merge_sales(ws["shows"][name], raw)
        ws["shows"][name] = merged
        msg = f"Added {added} sales to {name}"
        if skipped:
            msg += f" ({skipped} were already there, skipped)"
    else:
        ws["shows"][name] = raw
        msg = f"Replaced the sales for {name}" if exists else f"Added {name}"
    ws["unsaved"] = True
    return msg


def rename_show(ws: dict, old: str, new: str) -> None:
    ws["shows"] = {(new if k == old else k): v for k, v in ws["shows"].items()}
    exp = ws["expenses"].copy()
    exp.loc[exp["Show"] == old, "Show"] = new
    ws["expenses"] = exp
    ws["unsaved"] = True


def remove_show(ws: dict, name: str) -> None:
    ws["shows"].pop(name, None)
    ws["expenses"] = ws["expenses"][ws["expenses"]["Show"] != name].reset_index(drop=True)
    ws["unsaved"] = True


def set_expenses(ws: dict, df: pd.DataFrame) -> None:
    ws["expenses"] = clean_expenses(df)
    ws["unsaved"] = True


# --------------------------------------------------------------------------
# Save file
# --------------------------------------------------------------------------
def to_save_file(ws: dict) -> bytes:
    buf = io.BytesIO()
    used: set[str] = set()
    shows_rows = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if ws["inventory"] is not None:
            z.writestr("inventory.csv", ws["inventory"][1])
        for show, raw in ws["shows"].items():
            stem, n = _file_stem(show), 1
            fname = f"{stem}.csv"
            while fname.lower() in used:
                n += 1
                fname = f"{stem} ({n}).csv"
            used.add(fname.lower())
            z.writestr(f"sales/{fname}", raw)
            exp = ws["expenses"][ws["expenses"]["Show"] == show]
            if len(exp):
                for r in exp.itertuples(index=False):
                    shows_rows.append([show, fname, r.Category, f"{r.Amount:.2f}", r.Note])
            else:
                shows_rows.append([show, fname, "", "", ""])
        z.writestr("shows.csv",
                   pd.DataFrame(shows_rows, columns=SHOWS_FILE_COLS).to_csv(index=False))
    return buf.getvalue()


def from_save_file(raw: bytes) -> tuple[dict, list[str]]:
    """Read a save file. Returns (workspace, warnings)."""
    ws, warnings = _empty(), []
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValueError("That file isn't a save file. Save files are .zip files "
                         "downloaded from this dashboard.") from e

    # Find files regardless of a top-level folder inside the zip
    files: dict[str, bytes] = {}
    for info in z.infolist():
        if info.is_dir():
            continue
        p = PurePosixPath(info.filename)
        if p.name.startswith(".") or "__MACOSX" in p.parts:
            continue
        files[info.filename] = z.read(info)

    def find(name: str) -> str | None:
        return next((f for f in files if PurePosixPath(f).name.lower() == name), None)

    inv_path = find("inventory.csv")
    if inv_path:
        ws["inventory"] = ("inventory.csv", files[inv_path])

    sales_paths = {PurePosixPath(f).name: f for f in files
                   if "sales" in [x.lower() for x in PurePosixPath(f).parts[:-1]]
                   and f.lower().endswith(".csv")}

    shows_path = find("shows.csv")
    expense_rows = []
    named: set[str] = set()
    if shows_path:
        shows_df = read_str_csv(files[shows_path])
        for r in shows_df.to_dict("records"):
            show, fname = str(r.get("Show", "")).strip(), str(r.get("Sales file", "")).strip()
            if not show:
                continue
            if show not in ws["shows"]:
                if fname in sales_paths:
                    ws["shows"][show] = files[sales_paths[fname]]
                    named.add(fname)
                else:
                    ws["shows"][show] = empty_sales_csv()
                    if fname:
                        warnings.append(f"{fname} is missing from the save file, so {show} has no sales.")
            if str(r.get("Category", "")).strip() or str(r.get("Amount", "")).strip():
                expense_rows.append({"Show": show, "Category": r.get("Category", ""),
                                     "Amount": r.get("Amount", ""), "Note": r.get("Note", "")})

    # Any sales files not listed in shows.csv become shows named after the file
    for fname, path in sales_paths.items():
        if fname not in named:
            show = PurePosixPath(fname).stem
            if show not in ws["shows"]:
                ws["shows"][show] = files[path]

    ws["expenses"] = clean_expenses(pd.DataFrame(expense_rows, columns=EXPENSE_COLS)) \
        if expense_rows else empty_expenses()
    if is_empty(ws):
        raise ValueError("That save file doesn't contain an inventory or any shows.")
    return ws, warnings
