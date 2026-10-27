"""
Where the dashboard keeps its data.

- SheetsStore: one Google Sheet holds everything (used when Google credentials are in
  Streamlit secrets). Nothing is lost when the hosted app restarts.
- LocalStore: the app's data folder (used when running on your own computer without
  Google credentials).

Both expose the same methods, so app.py doesn't care which one it's using.

Google Sheet layout (tabs are created automatically):
    Inventory          your Collectr inventory export
    Sales - <show>     one tab per show, your Collectr transaction log export
    Expenses           expenses you log in the app
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

EXPENSE_COLS = ["Show", "Category", "Amount", "Note"]
INVENTORY_TAB = "Inventory"
EXPENSES_TAB = "Expenses"
SALES_PREFIX = "Sales - "


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def show_name_from_file(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else "Unnamed show"


def csv_to_rows(raw: bytes) -> list[list[str]]:
    df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                     engine="python", index_col=False)
    return [list(df.columns)] + df.astype(str).values.tolist()


def rows_to_csv(rows: list[list[str]]) -> bytes:
    """Sheet values (list of rows) -> CSV bytes the parsers understand."""
    if not rows:
        return b""
    header = [str(h).strip() for h in rows[0]]
    width = len(header)
    while width and not header[width - 1]:
        width -= 1
    if not width:
        return b""
    body = [(list(map(str, r)) + [""] * width)[:width] for r in rows[1:]]
    body = [r for r in body if any(c.strip() for c in r)]
    return pd.DataFrame(body, columns=header[:width]).to_csv(index=False).encode()


def clean_expenses(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in EXPENSE_COLS:
        if c not in df:
            df[c] = ""
    amount = df["Amount"].astype(str).str.replace(r"[,$\s]", "", regex=True)
    df["Amount"] = pd.to_numeric(amount, errors="coerce").fillna(0.0)
    for c in ["Show", "Category", "Note"]:
        df[c] = df[c].fillna("").astype(str).replace({"nan": "", "None": ""})
    df = df[df["Show"].str.strip() != ""]
    return df[EXPENSE_COLS].reset_index(drop=True)


def sheets_configured() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "sheets" in st.secrets
    except Exception:  # noqa: BLE001  (no secrets file at all)
        return False


def get_store():
    if sheets_configured():
        return SheetsStore(st.secrets["sheets"]["spreadsheet_url"])
    return LocalStore()


# --------------------------------------------------------------------------
# Local data folder
# --------------------------------------------------------------------------
class LocalStore:
    kind = "local"
    where = "data folder"
    link = None

    def __init__(self, app_dir: Path | None = None):
        self.data_dir = (app_dir or Path(__file__).parent) / "data"
        self.inventory_file = self.data_dir / "inventory.csv"
        self.sales_dir = self.data_dir / "sales"
        self.expenses_file = self.data_dir / "expenses.csv"
        self.names_file = self.data_dir / "show_names.csv"

    # show names chosen in the app, keyed by file name
    def _names(self) -> dict[str, str]:
        if not self.names_file.exists():
            return {}
        df = pd.read_csv(self.names_file, dtype=str, keep_default_na=False)
        return {r["File"]: r["Show"] for _, r in df.iterrows() if r.get("File") and r.get("Show")}

    def _file_shows(self) -> dict[str, str]:
        names = self._names()
        files = sorted(self.sales_dir.glob("*.csv")) if self.sales_dir.exists() else []
        return {p.name: names.get(p.name, show_name_from_file(p.name)) for p in files}

    def inventory(self) -> tuple[bytes | None, str | None]:
        if self.inventory_file.exists():
            return self.inventory_file.read_bytes(), self.inventory_file.name
        # fall back to any csv in data/ that looks like an inventory export
        if self.data_dir.exists():
            for p in sorted(self.data_dir.glob("*.csv")):
                if p.name in (self.expenses_file.name, self.names_file.name):
                    continue
                if "Market Price" in p.read_text(errors="ignore").split("\n", 1)[0]:
                    return p.read_bytes(), p.name
        return None, None

    def sales(self) -> dict[str, tuple[str, bytes]]:
        return {show: (f, (self.sales_dir / f).read_bytes())
                for f, show in self._file_shows().items()}

    def save_inventory(self, raw: bytes) -> None:
        self.data_dir.mkdir(exist_ok=True)
        self.inventory_file.write_bytes(raw)

    def save_sales(self, show: str, raw: bytes, file_name: str) -> None:
        self.sales_dir.mkdir(parents=True, exist_ok=True)
        (self.sales_dir / Path(file_name).name).write_bytes(raw)

    def rename_show(self, old: str, new: str) -> None:
        names = self._names()
        for f, show in self._file_shows().items():
            if show == old:
                names[f] = new
        self.data_dir.mkdir(exist_ok=True)
        pd.DataFrame({"File": list(names), "Show": list(names.values())}).to_csv(
            self.names_file, index=False)
        exp = self.expenses()
        if len(exp):
            exp.loc[exp["Show"] == old, "Show"] = new
            self.save_expenses(exp)

    def expenses(self) -> pd.DataFrame:
        if not self.expenses_file.exists():
            return pd.DataFrame(columns=EXPENSE_COLS).astype({"Amount": float})
        return clean_expenses(pd.read_csv(self.expenses_file, dtype=str, keep_default_na=False))

    def save_expenses(self, df: pd.DataFrame) -> None:
        self.data_dir.mkdir(exist_ok=True)
        clean_expenses(df).to_csv(self.expenses_file, index=False)

    def refresh(self) -> None:
        pass


# --------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _open_spreadsheet(url: str):
    import gspread

    client = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return client.open_by_url(url)


def _quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


@st.cache_data(ttl=600, show_spinner="Loading from Google Sheets…")
def _snapshot(url: str) -> dict[str, list[list[str]]]:
    """All tabs the app uses, read in a single API call."""
    book = _open_spreadsheet(url)
    titles = [ws.title for ws in book.worksheets()]
    wanted = [t for t in titles
              if t in (INVENTORY_TAB, EXPENSES_TAB) or t.startswith(SALES_PREFIX)]
    if not wanted:
        return {}
    resp = book.values_batch_get([_quote(t) for t in wanted])
    ranges = resp.get("valueRanges", [])
    return {t: vr.get("values", []) for t, vr in zip(wanted, ranges)}


class SheetsStore:
    kind = "sheets"
    where = "Google Sheets"

    def __init__(self, url: str):
        self.url = url
        self.link = url

    @property
    def service_email(self) -> str:
        try:
            return st.secrets["gcp_service_account"]["client_email"]
        except Exception:  # noqa: BLE001
            return "your service account"

    def check(self) -> None:
        """Raise a clear error if the sheet can't be opened."""
        _open_spreadsheet(self.url)

    def _snap(self) -> dict[str, list[list[str]]]:
        return _snapshot(self.url)

    def _write_tab(self, title: str, rows: list[list[str]]) -> None:
        import gspread

        width = max((len(r) for r in rows), default=1) or 1
        rows = [[str(c) for c in r] + [""] * (width - len(r)) for r in rows]
        n_rows = max(len(rows), 1) + 5
        book = _open_spreadsheet(self.url)
        try:
            ws = book.worksheet(title)
            ws.clear()
            ws.resize(rows=n_rows, cols=width)
        except gspread.WorksheetNotFound:
            ws = book.add_worksheet(title=title, rows=n_rows, cols=width)
        if rows:
            ws.update(values=rows, range_name="A1", value_input_option="RAW")

    def inventory(self) -> tuple[bytes | None, str | None]:
        rows = self._snap().get(INVENTORY_TAB)
        raw = rows_to_csv(rows) if rows else b""
        return (raw, f"{INVENTORY_TAB} tab") if raw else (None, None)

    def sales(self) -> dict[str, tuple[str, bytes]]:
        out = {}
        for title, rows in self._snap().items():
            if title.startswith(SALES_PREFIX):
                raw = rows_to_csv(rows)
                if raw:
                    out[title[len(SALES_PREFIX):].strip()] = (f"{title} tab", raw)
        return out

    def save_inventory(self, raw: bytes) -> None:
        self._write_tab(INVENTORY_TAB, csv_to_rows(raw))
        self.refresh()

    def save_sales(self, show: str, raw: bytes, file_name: str) -> None:
        self._write_tab(SALES_PREFIX + show, csv_to_rows(raw))
        self.refresh()

    def rename_show(self, old: str, new: str) -> None:
        book = _open_spreadsheet(self.url)
        book.worksheet(SALES_PREFIX + old).update_title(SALES_PREFIX + new)
        exp = self.expenses()
        if len(exp):
            exp.loc[exp["Show"] == old, "Show"] = new
            self.save_expenses(exp)
        self.refresh()

    def expenses(self) -> pd.DataFrame:
        rows = self._snap().get(EXPENSES_TAB)
        raw = rows_to_csv(rows) if rows else b""
        if not raw:
            return pd.DataFrame(columns=EXPENSE_COLS).astype({"Amount": float})
        return clean_expenses(pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False))

    def save_expenses(self, df: pd.DataFrame) -> None:
        df = clean_expenses(df)
        rows = [EXPENSE_COLS] + [[r.Show, r.Category, f"{r.Amount:.2f}", r.Note]
                                 for r in df.itertuples(index=False)]
        self._write_tab(EXPENSES_TAB, rows)
        self.refresh()

    def refresh(self) -> None:
        _snapshot.clear()
