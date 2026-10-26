# Card Show Ledger

A Streamlit dashboard for trading card vendors. Drop in your [Collectr](https://getcollectr.com) exports and see what you actually made at each card show: realized profit, unrealized profit on the cards still in your binder, show expenses, and charts that show where your money is.

<!-- Add a screenshot: save one as docs/screenshot.png and uncomment the line below.
![Dashboard overview](docs/screenshot.png)
-->

## What it does

- **Answers "did I make money?"** with net profit across your selected shows, after cost of cards sold and show expenses.
- **Tracks realized and unrealized profit separately.** Realized comes from your sold exports; unrealized compares what you paid for your current stock against today's market value.
- **Breaks results down by show.** Each sold export becomes its own show, so you can compare shows and decide which are worth the table fee.
- **Logs show expenses** (table fees, gas, hotel, food, supplies) right in the app, since Collectr doesn't export them.
- **Filters everything** by show, game, portfolio, and gains or losses.
- **Charts the useful stuff:** profit on every card sold, running totals by date, raw vs graded revenue, profit by grade, holding time vs profit, biggest unrealized winners and losers, value by portfolio, and how concentrated your value is in a few cards.
- **Keeps the source files at hand** on a Files tab, with download buttons.

## Getting started

### Requirements

- Python 3.10 or newer
- A Collectr inventory export (CSV) and one sold export (CSV) per show

### Install

```bash
git clone https://github.com/<your-username>/card-show-ledger.git
cd card-show-ledger

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Run

```bash
python -m streamlit run app.py
```

The dashboard opens in your browser at `http://localhost:8501`. Next time, you only need to activate the virtual environment and run that command.

## Adding your data

Export your data from Collectr as CSV, then either drag the files into the uploaders in the app's sidebar or put them in the `data` folder so they load automatically:

```
data/
├── inventory.csv          # your Collectr inventory export
└── sales/
    ├── Bossa show.csv     # one Collectr sold export per show
    └── Spring expo.csv
```

Create the folders the first time with `mkdir -p data/sales`. Files uploaded in the sidebar can be kept for next time with **Save uploads to data folder**.

Each sold file becomes a show, named after the file. You can rename a show inside the app at any time.

### Before each show

Export a fresh inventory from Collectr and replace `data/inventory.csv`, so market values are current.

### After each show

1. Export the cards you sold that day from Collectr and save the file in `data/sales/`.
2. Open the **Shows & expenses** tab and log your table fee and other costs, then click **Save expenses**.
3. Check the headline number for your net profit.

## Using the dashboard

### Filters (sidebar)

| Filter | What it does |
| --- | --- |
| Card show | Choose which shows count toward sales and expenses. |
| Game | Pokémon, Riftbound, or whatever games are in your exports. |
| Portfolio | Limit to specific Collectr portfolios. |
| Hide personal collection | Hides any portfolio with "PC" in its name, so only for-sale stock counts. |
| Results | Show all cards, only gains, or only losses. |
| Leave out $0-cost cards | Excludes cards with no cost entered, which otherwise count their full value as gain. |

### Tabs

- **Overview:** results for each show and where your inventory value sits.
- **Realized:** every sale, best and worst sales, profit by grade, and whether holding longer paid off.
- **Unrealized:** biggest gainers and losers, value by game, type, grade or condition, and a searchable inventory table.
- **Shows & expenses:** a results table for each show, the expense log, and show renaming.
- **Files:** your original exports, viewable and downloadable.

### Renaming a show

On **Shows & expenses**, open **Rename a show**, pick the show, type the new name, and click **Rename**. The new name is used everywhere, and any expenses logged under the old name move with it. Your exported file keeps its original name.

## How the numbers work

- **Market value** uses Collectr's market price, or your price override when you've set one in Collectr.
- **Cards with a market price of 0** have no price data in Collectr. They're left out of market value and unrealized profit, and the app tells you how many there are. Set a price override in Collectr to include them.
- **Unrealized profit** is market value minus what you paid, for cards still in your inventory.
- **Realized profit** is sold price minus purchase price, times quantity, for each card in your sold exports.
- **Net profit** is realized profit minus the expenses you log for those shows.
- **Cards with a $0 cost** count their full market value as gain. Use the filter to see results without them.

## Project structure

```
card-show-ledger/
├── app.py                 # the Streamlit app
├── requirements.txt
├── .streamlit/
│   └── config.toml        # theme and settings
└── data/                  # your files (ignored by git)
    ├── inventory.csv
    ├── sales/
    ├── expenses.csv       # written by the app
    └── show_names.csv     # written by the app
```

To change or remove the links shown on the Files tab, edit `SOURCE_LINKS` near the top of `app.py`.

## Privacy

Your exports contain your full collection and what you paid for it. The `.gitignore` keeps everything in `data/` out of the repository, so your card data stays on your computer. If you want to back up your data to GitHub, remove that line from `.gitignore` and keep the repository private.

## Troubleshooting

**`error: externally-managed-environment` when running pip**
Your system Python doesn't allow direct installs. Create and activate the virtual environment as shown in [Install](#install), then use `python -m pip install`.

**`command not found: streamlit` or `No module named streamlit`**
The virtual environment isn't active, or the install didn't finish. Run `source .venv/bin/activate`, then `python -m pip install -r requirements.txt`, then `python -m streamlit run app.py`.

**`nodename nor servname provided, or not known` during install**
pip can't reach the internet. Check your connection, turn off any VPN, or try another network, then run the install again.

**A card shows no market value**
Collectr has no price for it. Set a price override in Collectr and re-export.

## Built with

[Streamlit](https://streamlit.io), [pandas](https://pandas.pydata.org), and [Plotly](https://plotly.com/python/).
