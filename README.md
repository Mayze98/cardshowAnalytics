# Card Show Ledger

A Streamlit dashboard for trading card vendors. Drop in your [Collectr](https://getcollectr.com) exports and see what you actually made at each card show: realized profit, unrealized profit on the cards still in your binder, show expenses, and charts that show where your money is.

**Live app:** [cardshowanalytics.streamlit.app](https://cardshowanalytics.streamlit.app/)

<!-- Add a screenshot: save one as docs/screenshot.png and uncomment the line below.
![Dashboard overview](docs/screenshot.png)
-->

## What it does

- **Answers "did I make money?"** with net profit across your selected shows, after cost of cards sold and show expenses.
- **Tracks realized and unrealized profit separately.** Realized comes from your Collectr transaction log; unrealized compares what you paid for your current stock against today's market value.
- **Breaks results down by show.** Each transaction log export becomes its own show, so you can compare shows and decide which are worth the table fee.
- **Logs show expenses** (table fees, gas, hotel, food, supplies) right in the app, since Collectr doesn't export them.
- **Filters everything** by show, game, portfolio, and gains or losses.
- **Charts the useful stuff:** profit on every card sold, running totals by date, raw vs graded revenue, profit by grade, holding time vs profit, biggest unrealized winners and losers, value by portfolio, and how concentrated your value is in a few cards.
- **Saves your data to Google Sheets,** so nothing is lost when the hosted app restarts.

## Where your data is stored

The app keeps your exports, expenses and show names in one of two places:

| Mode | When it's used | Where data lives |
| --- | --- | --- |
| **Google Sheets** | Google credentials are set in Streamlit secrets | One Google Sheet in your Google account |
| **Local** | No Google credentials (e.g. running on your computer for the first time) | The `data` folder next to `app.py` |

Use Google Sheets for the hosted app. Streamlit Community Cloud wipes the app's disk whenever it restarts, so local mode only makes sense on your own computer.

In Google Sheets mode, the app creates and manages these tabs:

| Tab | Contents |
| --- | --- |
| `Inventory` | Your latest Collectr inventory export |
| `Sales - <show name>` | One tab per show, from your Collectr transaction log |
| `Expenses` | The expenses you log in the app |

You can open the sheet and edit it directly. Click **Reload from Google Sheets** in the app's sidebar afterward to see your changes.

## Getting started

### Requirements

- Python 3.10 or newer
- A [Collectr PRO](https://getcollectr.com/pro) membership, for exports
- A Google account, for Google Sheets storage

### Install

```bash
git clone https://github.com/Mayze98/cardshowAnalytics.git
cd cardshowAnalytics

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Run

```bash
python -m streamlit run app.py
```

The dashboard opens in your browser at `http://localhost:8501`. Next time, you only need to activate the virtual environment and run that command.

## Setting up Google Sheets storage

This takes about 15 minutes, once. You create a Google "service account" (a robot user the app signs in as), give it access to one Google Sheet, and hand its key to Streamlit as a secret.

### 1. Create a service account

1. Go to the [Google Cloud console](https://console.cloud.google.com/) and create a new project (for example "Card Show Ledger").
2. Open **APIs & Services → Library**, search for **Google Sheets API**, and click **Enable**.
3. Open **IAM & Admin → Service Accounts** and click **Create service account**. Give it a name and click through; it doesn't need any roles.
4. Open the new service account, go to the **Keys** tab, and choose **Add key → Create new key → JSON**. A JSON file downloads. Keep it safe; it's a password.

### 2. Create the Google Sheet

1. Create a new, blank Google Sheet (for example "Card Show Ledger data").
2. Click **Share** and add the service account's email address (the `client_email` in the JSON file, ending in `iam.gserviceaccount.com`) as an **Editor**.
3. Copy the sheet's URL from your browser.

### 3. Add the secrets

The app reads its settings from Streamlit secrets. Use [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) as a template:

- `spreadsheet_url`: the sheet URL you copied.
- `[gcp_service_account]`: copy each value from the JSON key file. Keep `private_key` on one line, with the `\n` sequences exactly as they appear in the JSON.
- `app_password` (optional, recommended): a password the app asks for before showing anything.

**On Streamlit Community Cloud:** open your app, go to **Settings → Secrets**, paste the filled-in contents, and save. The app restarts and connects.

**On your computer:** save the filled-in file as `.streamlit/secrets.toml`. It's listed in `.gitignore`, so it won't be committed. Never commit this file or the JSON key to GitHub.

### 4. Load your data

Open the app, upload your Collectr inventory export and a transaction log export for each show in the sidebar, and click **Save uploads to Google Sheets**. From then on, the app loads everything from the sheet automatically.

## Exporting from Collectr

The dashboard reads two kinds of CSV files from Collectr: your **inventory** (everything you own right now) and your **transaction log** (cards you've marked as sold).

### Inventory

1. Open Collectr and go to the **Portfolio** screen.
2. Tap the **three dots** in the top right and select **Export**.
3. Enter your email address. Collectr emails you the export as a CSV file.
4. Download the CSV from the email.

Export all your portfolios, not just one. The dashboard uses your portfolio names for its filters and charts, and the **Hide personal collection** filter looks for portfolios with "PC" in the name.

### Sales

1. When you sell a card, mark it as sold in Collectr and enter the sold price and date. The dashboard calculates profit from your purchase price and sold price, so both need to be filled in.
2. After the show, open **View transaction log** in Collectr.
3. Tap **Export to CSV**.
4. Name the file after the show (for example `Spring expo.csv`). The file name becomes the show's name in the dashboard.

Each transaction log file counts as one show. If your export includes sales from other days or other shows, open it in a spreadsheet app, delete those rows, and save it as CSV before adding it.

### What the files need to contain

If a file won't load, check that it has these columns (the names must match Collectr's export):

| File | Required columns |
| --- | --- |
| Inventory | Portfolio Name, Category, Set, Product Name, Grade, Average Cost Paid, Quantity, Market Price (As of …), Price Override, Date Added |
| Transaction log | Portfolio Name, Product Name, Grade, Quantity, Purchase Price, Purchase Date, Sold Price, Sold Date |

## Adding your data

Upload your CSV files in the app's sidebar, then click **Save uploads to Google Sheets** (or **Save uploads to data folder** in local mode) so they're kept. Without saving, uploads only last until you close the tab.

In local mode you can also copy the files into the `data` folder yourself:

```
data/
├── inventory.csv          # your Collectr inventory export
└── sales/
    ├── Bossa show.csv     # one transaction log export per show
    └── Spring expo.csv
```

### Before each show

Upload a fresh inventory export and save it, so market values are current. It replaces the previous inventory.

### After each show

1. Export the show's transaction log from Collectr, upload it, and save it.
2. Open the **Shows & expenses** tab, log your table fee and other costs, and click **Save expenses**.
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
- **Files:** your stored exports, viewable and downloadable.

### Renaming a show

On **Shows & expenses**, open **Rename a show**, pick the show, type the new name, and click **Rename**. The new name is used everywhere, and any expenses logged under the old name move with it. In Google Sheets mode, the show's tab is renamed too.

### Removing a show

In Google Sheets mode, delete the show's `Sales - …` tab in the sheet, then click **Reload from Google Sheets**. In local mode, delete its file from `data/sales/`.

## How the numbers work

- **Market value** uses Collectr's market price, or your price override when you've set one in Collectr.
- **Cards with a market price of 0** have no price data in Collectr. They're left out of market value and unrealized profit, and the app tells you how many there are. Set a price override in Collectr to include them.
- **Unrealized profit** is market value minus what you paid, for cards still in your inventory.
- **Realized profit** is sold price minus purchase price, times quantity, for each card in your transaction logs.
- **Net profit** is realized profit minus the expenses you log for those shows.
- **Cards with a $0 cost** count their full market value as gain. Use the filter to see results without them.

## Project structure

```
cardshowAnalytics/
├── app.py                        # the dashboard
├── storage.py                    # saves and loads data (Google Sheets or local folder)
├── requirements.txt
├── .streamlit/
│   ├── config.toml               # theme and settings
│   ├── secrets.toml.example      # template for your secrets
│   └── secrets.toml              # your real secrets (ignored by git)
└── data/                         # local mode only (ignored by git)
```

## Privacy

Your exports contain your full collection and what you paid for it.

- **In the repository:** `.gitignore` keeps `data/` and `.streamlit/secrets.toml` out of GitHub, so no card data or keys are committed.
- **In Google Sheets:** the sheet is private to your Google account and the service account you shared it with.
- **In the hosted app:** the app loads your data for anyone who opens it. Set `app_password` in secrets, or make the app private in Streamlit Community Cloud under **Settings → Sharing**.

## Troubleshooting

**"Couldn't open your Google Sheet"**
Check that `spreadsheet_url` in secrets is the sheet's full URL, that the sheet is shared with the service account's email as an Editor, and that the Google Sheets API is enabled in your Google Cloud project.

**Changes made in the Google Sheet don't show up**
The app keeps a copy of the sheet for 10 minutes to stay fast. Click **Reload from Google Sheets** in the sidebar.

**Expenses or uploads disappeared from the hosted app**
The app is running in local mode, which Streamlit Community Cloud wipes on restart. Set up [Google Sheets storage](#setting-up-google-sheets-storage).

**`error: externally-managed-environment` when running pip**
Your system Python doesn't allow direct installs. Create and activate the virtual environment as shown in [Install](#install), then use `python -m pip install`.

**`command not found: streamlit` or `No module named streamlit`**
The virtual environment isn't active, or the install didn't finish. Run `source .venv/bin/activate`, then `python -m pip install -r requirements.txt`, then `python -m streamlit run app.py`.

**`nodename nor servname provided, or not known` during install**
pip can't reach the internet. Check your connection, turn off any VPN, or try another network, then run the install again.

**A card shows no market value**
Collectr has no price for it. Set a price override in Collectr and re-export.

## Built with

[Streamlit](https://streamlit.io), [pandas](https://pandas.pydata.org), [Plotly](https://plotly.com/python/), and [gspread](https://docs.gspread.org/).
