# Card Show Ledger

A Streamlit dashboard for trading card vendors. Load your [Collectr](https://getcollectr.com) exports and see what you actually made at each card show: realized profit, unrealized profit on the cards still in your binder, show expenses, and charts that show where your money is.

**Live app:** [cardshowanalytics.streamlit.app](https://cardshowanalytics.streamlit.app/)

<!-- Add a screenshot: save one as docs/screenshot.png and uncomment the line below.
![Dashboard overview](docs/screenshot.png)
-->

## What it does

- **Answers "did I make money?"** with net profit across your selected shows, after cost of cards sold and show expenses.
- **Tracks realized and unrealized profit separately.** Realized comes from your Collectr transaction logs; unrealized compares what you paid for your current stock against today's market value.
- **Breaks results down by show,** so you can compare shows and decide which are worth the table fee.
- **Logs show expenses** (table fees, gas, hotel, food, supplies) right in the app, since Collectr doesn't export them.
- **Filters everything** by show, game, portfolio, and gains or losses.
- **Charts the useful stuff:** profit on every card sold, running totals by date, raw vs graded revenue, profit by grade, holding time vs profit, biggest unrealized winners and losers, value by portfolio, and how concentrated your value is in a few cards.
- **Keeps your data on your computer.** Nothing is stored online; you keep a save file and open it next time.

## How your data is saved

The dashboard doesn't store anything on the server. Your data lives in your browser session while the dashboard is open, and you keep it between sessions with a **save file**:

1. When you're done, click **Download save file** in the sidebar. You get a `.zip` file, for example `card-show-ledger-2026-10-26.zip`.
2. Next time, open the dashboard and upload that file under **Open save file**. Everything comes back: your inventory, your shows and their sales, and your expenses.

The sidebar tells you when you have changes that aren't in a save file yet. Closing or refreshing the tab without downloading loses those changes.

Inside the save file:

| File | Contents |
| --- | --- |
| `inventory.csv` | Your Collectr inventory export |
| `shows.csv` | Your shows and their expenses |
| `sales/<show>.csv` | One Collectr transaction log per show |

These are ordinary CSV files, so you can unzip the save file and open them in any spreadsheet app.

Because nothing is stored online, it's safe to leave the hosted app public. Other visitors only ever see their own session.

## Getting started

### Requirements

- A [Collectr PRO](https://getcollectr.com/pro) membership, for exports
- To run it on your own computer: Python 3.10 or newer

### Use the hosted app

Open [cardshowanalytics.streamlit.app](https://cardshowanalytics.streamlit.app/). Nothing to install.

### Run it on your computer

```bash
git clone https://github.com/Mayze98/cardshowAnalytics.git
cd cardshowAnalytics

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The dashboard opens in your browser at `http://localhost:8501`. Next time, you only need to activate the virtual environment and run the last command.

## Exporting from Collectr

The dashboard reads two kinds of CSV files from Collectr: your **inventory** (everything you own right now) and your **transaction log** (cards you've marked as sold).

### Inventory

1. Open Collectr and go to the **Portfolio** screen.
2. Tap the **three dots** in the top right and select **Export**.
3. Enter your email address. Collectr emails you the export as a CSV file.
4. Download the CSV from the email.

Export all your portfolios, not just one. The dashboard uses your portfolio names for its filters and charts, and the **Hide personal collection** filter looks for portfolios with "PC" in the name.

### Transaction log

1. When you sell a card, mark it as sold in Collectr and enter the sold price and date. The dashboard calculates profit from your purchase price and sold price, so both need to be filled in.
2. After the show, open **View transaction log** in Collectr.
3. Tap **Export to CSV**.

If your export includes sales from other days or other shows, open it in a spreadsheet app, delete those rows, and save it as CSV before adding it.

### What the files need to contain

If a file won't load, check that it has these columns (the names must match Collectr's export):

| File | Required columns |
| --- | --- |
| Inventory | Portfolio Name, Category, Set, Product Name, Grade, Average Cost Paid, Quantity, Market Price (As of …), Price Override, Date Added |
| Transaction log | Portfolio Name, Product Name, Grade, Quantity, Purchase Price, Purchase Date, Sold Price, Sold Date |

## Using the dashboard

### First time

1. Upload your Collectr inventory export in the sidebar under **Collectr inventory export**.
2. Add your shows (see below).
3. Click **Download save file** and keep the file somewhere safe.

### Before each show

1. Open your save file.
2. Upload a fresh inventory export so market values are current. It replaces the previous inventory.
3. Optionally add the show now, without a file, so you can log its table fee.
4. Download your save file.

### After each show

1. Open your save file.
2. Add the show's transaction log with **Add a show**.
3. Log your table fee and other costs under **Expenses** and click **Update expenses**.
4. Check the headline number for your net profit.
5. Download your save file.

### Adding a show

On the **Shows & expenses** tab, open **Add a show**:

1. Type the show's name.
2. Attach the show's Collectr transaction log, or leave it empty to create the show now and add sales later.
3. Click **Add show**.

To add more sales to a show you already created (for example the second day of a weekend show), use the same show name and choose **Add these sales to it**. Sales that are already there are skipped, so adding the same transaction log twice won't double count. Choose **Replace its sales** to start that show over with the new file.

### Renaming or removing a show

On **Shows & expenses**, open **Rename or remove a show** and pick the show. Renaming moves its expenses with it. To remove a show, tick the confirmation box and click **Remove show**; its expenses are removed too.

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
- **Shows & expenses:** add, rename and remove shows, a results table for each show, and the expense log.
- **Files:** the Collectr exports in your current session, each downloadable on its own.

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
├── app.py              # the dashboard
├── workspace.py        # session data and the save file
├── requirements.txt
└── .streamlit/
    └── config.toml     # theme and settings
```

`.gitignore` excludes `.zip` files, so a save file kept in the project folder won't be committed by accident.

## Troubleshooting

**My data is gone after refreshing the page**
The dashboard only keeps data until the tab is closed or refreshed. Open your latest save file. Download a new save file whenever the sidebar says you have unsaved changes.

**"That file isn't a save file"**
Upload the `.zip` you downloaded from the dashboard, not one of the CSV files inside it. To load a single Collectr export, use **Collectr inventory export** in the sidebar or **Add a show**.

**`error: externally-managed-environment` when running pip**
Your system Python doesn't allow direct installs. Create and activate the virtual environment as shown above, then use `python -m pip install`.

**`command not found: streamlit` or `No module named streamlit`**
The virtual environment isn't active, or the install didn't finish. Run `source .venv/bin/activate`, then `python -m pip install -r requirements.txt`, then `python -m streamlit run app.py`.

**`nodename nor servname provided, or not known` during install**
pip can't reach the internet. Check your connection, turn off any VPN, or try another network, then run the install again.

**A card shows no market value**
Collectr has no price for it. Set a price override in Collectr and re-export.

## Built with

[Streamlit](https://streamlit.io), [pandas](https://pandas.pydata.org), and [Plotly](https://plotly.com/python/).
