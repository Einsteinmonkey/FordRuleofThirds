# FordRuleofThirds

Automated **Ford Motor Company (NYSE: F)** Rule of Thirds dashboard for:

1. **3m**
2. **15m**
3. **30m**
4. **1h**
5. **1d**

Each candle is displayed in this exact order:

1. **1st** = Low + 1/3 of the candle range
2. **2nd** = Low + 2/3 of the candle range
3. **3rd** = High

Where:

```text
Range = High - Low
One Third = Range / 3
```

The dashboard keeps the **last 20 fully closed candles** for every timeframe.

## Why the 3-minute timeframe is aggregated

Yahoo Finance does not expose a native 3-minute chart interval. The script downloads regular-session **1-minute** Ford candles and aggregates them into **3m, 15m, 30m, and 1h** candles. The **1d** timeframe uses Yahoo daily candles.

Regular NYSE session used by the script: **9:30 AM–4:00 PM ET**.

## Files

- `calculate_rule_of_thirds.py` — downloads Ford data, calculates 1st/2nd/3rd levels, and regenerates outputs.
- `index.html` — GitHub Pages dashboard.
- `results/latest.md` — Markdown tables for all five timeframes.
- `results/history.csv` — combined CSV history.
- `.github/workflows/update-rule-of-thirds.yml` — automatic refresh every 5 minutes on weekdays plus manual runs.

## Create the GitHub repository

Recommended repository name:

```text
FordRuleofThirds
```

1. Create a new GitHub repository named `FordRuleofThirds`.
2. Upload all files from this package, including the `.github` folder.
3. Open **Actions** in GitHub and run **Update Ford Rule of Thirds** once using **Run workflow**.
4. After the action finishes, `index.html`, `results/latest.md`, and `results/history.csv` will contain current Ford data.
5. To publish the dashboard, go to **Settings → Pages** and choose **Deploy from a branch → main → /(root)**.

## Automation

The GitHub Action runs every 5 minutes Monday through Friday. GitHub scheduled workflows cannot reliably run every 3 minutes, but every run recalculates the latest fully closed 3-minute candle.

## Data source

Yahoo Finance chart data for ticker `F`.

> Informational use only. This project is not financial advice.
