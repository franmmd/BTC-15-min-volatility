# BTC‑15‑min‑volatility

Repository containing the scripts to fetch price data, compute 15 minute volatility for Bitcoin, Ethereum, Solana and Monero, store it in SQLite and generate weekly reports with max/mean/min graphs.

- `btc_15min_volatility.py` – daily script (creates/updates `vol_15m` table).
- `populate_dummy_volatility.py` – helper to generate dummy historic rows.
- `weekly_volatility_report.py` – generates a weekly Telegram report.
