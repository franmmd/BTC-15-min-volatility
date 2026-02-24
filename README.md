# BTC Volatility Report (15‑min)

Este repositorio contiene el script `btc_15min_volatility.py` que:

- Descarga precios de Bitcoin (CoinGecko) con resolución de 1 min.
- Calcula la volatilidad (desviación estándar) en bloques de 15 min.
- Almacena 96 valores diarios en una tabla SQLite.
- Envía una gráfica y un resumen a Telegram.

Puedes ejecutarlo manualmente o programarlo con cron.

```bash
chmod +x btc_15min_volatility.py
./btc_15min_volatility.py
