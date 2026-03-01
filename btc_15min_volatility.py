#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
btc_15min_volatility.py

Este script se ejecuta diariamente (por ejemplo a la medianoche) y:
  1. Descarga los precios de Bitcoin (USD) en intervalos de 1 minuto
     para todo el día anterior usando la API pública de CoinGecko.
  2. Re-muestrea los datos a intervalos de 15 minutos (último precio
     de cada cuartohora).
  3. Calcula la volatilidad basada en retornos log‑aritmicos de esos
     intervalos de 15 minutos.
  4. Guarda el valor en una tabla SQLite.
  5. Envía una notificación por Telegram con el resultado.

Requisitos: python3, requests, pandas. Instale con:
  pip install requests pandas

Para que el mensaje de Telegram funcione, debe:
  • Tener el token del bot configurado en ~/.openclaw/openclaw.json
  • Conocer su chat_id (puede obtenerlo enviando cualquier mensaje al bot
    y ejecutando `curl .../getUpdates`).
  • Exportar la variable de entorno TELEGRAM_CHAT_ID con su chat_id antes
    de que el cron ejecute el script.
"""

import datetime as dt
import json
import os
import sys
import matplotlib.pyplot as plt
import tempfile
import numpy as np
from pathlib import Path
import pandas as pd

import os
import json
import requests
import sqlite3
DB_PATH = Path.home() / ".openclaw" / "btc_volatility.sqlite"
TABLE = "vol_15m"
COINGECKO_API = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
TOKEN = None  # se leerá del archivo de configuración de OpenClaw
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # debe estar definido en el entorno
# ------------------------------------------------------------------
def load_bot_token():
    """Lee el token del bot desde openclaw.json (ruta conocida)."""
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        cfg = json.loads(cfg_path.read_text())
        return cfg["channels"]["telegram"]["botToken"]
    except Exception as e:
        print(f"❌ No se pudo leer el token del bot: {e}", file=sys.stderr)
        sys.exit(1)

def get_unix_timestamp(dt_obj: dt.datetime) -> int:
    return int(dt_obj.timestamp())

def fetch_price_data(asset_id: str, start_ts: int, end_ts: int) -> pd.Series:
    """Descarga los precios en USD para el activo indicado (asset_id) entre start_ts y end_ts.
    asset_id debe coincidir con el identificador de CoinGecko (e.g. "bitcoin" o "ethereum")."""
    url = f"https://api.coingecko.com/api/v3/coins/{asset_id}/market_chart/range"
    params = {"vs_currency": "usd", "from": start_ts, "to": end_ts}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["prices"]  # [[ts_ms, price], ...]
    df = pd.DataFrame(data, columns=["ts_ms", "price_usd"])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    # Re‑muestrear a 15 minutos, tomando el último precio de cada ventana
    return df["price_usd"]

def compute_15min_volatility(series: pd.Series) -> pd.Series:
    """Calcula la volatilidad (desviación estándar) de los retornos logarítmicos en bloques de 15 min.
    Devuelve una Serie indexada por el inicio de cada bloque con el valor de volatilidad.
    Los valores NaN se sustituyen por 0.0.
    """
    log_ret = np.log(series / series.shift(1)).dropna()
    vol_series = log_ret.resample('15min').std().fillna(0.0)
    # Asegura 96 valores
    if len(vol_series) < 96:
        extra = pd.Series([0.0]*(96 - len(vol_series)), index=pd.date_range(start=vol_series.index[-1] + pd.Timedelta(minutes=15), periods=96 - len(vol_series), freq='15min'))
        vol_series = pd.concat([vol_series, extra])
    return vol_series.head(96)

def init_db(conn: sqlite3.Connection):
    # Crea la tabla si no existe, manteniendo datos históricos.
    cols = ", ".join([f"v{i} REAL" for i in range(96)])
    sql = f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            day TEXT,
            asset TEXT,
            {cols},
            computed_at TIMESTAMP NOT NULL,
            PRIMARY KEY(day, asset)
        );
    """
    conn.execute(sql)
    conn.commit()

def store_results(conn: sqlite3.Connection, day: str, asset: str, series: pd.Series):
    """Inserta una fila con la volatilidad de cada tramo de 15 min para un activo.
    *series* debe contener 96 valores (uno por cada tramo) y su índice será el comienzo del tramo.
    """
    # Aseguramos 96 valores; si faltan, completamos con None
    values = [float(series.iloc[i]) if i < len(series) and not pd.isna(series.iloc[i]) else None for i in range(96)]
    placeholders = ", ".join(["?" for _ in range(98)])  # day, asset + 96 slots
    sql = f"INSERT INTO {TABLE} (day, asset, " + ", ".join([f"v{i}" for i in range(96)]) + ", computed_at) "
    sql += f"VALUES ({placeholders}, CURRENT_TIMESTAMP)"
    conn.execute(sql, (day, asset, *values))
    conn.commit()

def send_telegram_message(token: str, chat_id: str, text: str = None, image_path: str = None):
    """Envía un mensaje de texto o una foto a Telegram.
    Si *image_path* está definido se envía la foto con *caption* opcional (text).
    """
    # Decide endpoint según si hay imagen
    if image_path:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id}
    if text:
        if image_path:
            payload["caption"] = text
        else:
            payload["text"] = text
            payload["parse_mode"] = "Markdown"
    try:
        if image_path:
            with open(image_path, "rb") as f:
                files = {"photo": f}
                r = requests.post(url, data=payload, files=files, timeout=10)
        else:
            r = requests.post(url, data=payload, timeout=10)
        r.raise_for_status()
        print("✅ Notificación enviada a Telegram")
    except Exception as e:
        print(f"❌ Error enviando mensaje Telegram: {e}", file=sys.stderr)

def main():
    global TOKEN
    TOKEN = load_bot_token()
    if not CHAT_ID:
        print("❌ La variable de entorno TELEGRAM_CHAT_ID no está definida.", file=sys.stderr)
        sys.exit(1)

    today_utc = dt.datetime.utcnow().date()
    target_day = today_utc - dt.timedelta(days=1)
    start_dt = dt.datetime.combine(target_day, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(target_day, dt.time.max, tzinfo=dt.timezone.utc)
    start_ts = get_unix_timestamp(start_dt)
    end_ts = get_unix_timestamp(end_dt)

    assets = [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"), ("monero", "XMR")]
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    for asset_id, asset_label in assets:
        # Descargar precios y calcular volatilidad para el activo actual
        prices_series = fetch_price_data(asset_id, start_ts, end_ts)
        vol_series = compute_15min_volatility(prices_series)
        # Guardar resultados con el identificador del activo
        store_results(conn, target_day.isoformat(), asset_label, vol_series)
        # Recuperar la fila insertada para incluir datos en el mensaje
        row = conn.execute(f"SELECT * FROM {TABLE} WHERE day = ? AND asset = ?", (target_day.isoformat(), asset_label)).fetchone()
        # Preparar una pequeña tabla de los primeros 5 tramos para el mensaje
        snippet_vals = []
        for i in range(5):
            val = row[2 + i]  # offset: day(0), asset(1), then v0 starts at index 2
            snippet_vals.append(f"v{i}:{val:.6f}" if val is not None else f"v{i}:N/A")
        snippet_text = ", ".join(snippet_vals)
        # Generar gráfico de volatilidad por ventana de 15 min
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(vol_series.index, vol_series.values, marker='o', linestyle='-')
        ax.set_title(f"Volatilidad {asset_label} (15 min) – {target_day}")
        ax.set_xlabel('Hora (UTC)')
        ax.set_ylabel('Volatilidad (σ)')
        ax.grid(True)
        # Guardar en archivo temporal
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            fig.savefig(tmp.name, bbox_inches='tight')
            plot_path = tmp.name
        plt.close(fig)
        msg = f"*Volatilidad {asset_label} (15 min) – {target_day}*\nVentanas: `{len(vol_series)}`\nVolatilidad media: `{vol_series.mean():.6f}`\nDatos (primeros 5 tramos): `{snippet_text}`"
        # Envío de foto con caption (el caption lleva el mismo texto)
        send_telegram_message(TOKEN, CHAT_ID, text=msg, image_path=plot_path)
        # Opcional: eliminar el archivo temporal
        try:
            os.remove(plot_path)
        except Exception:
            pass
        print(f"[{dt.datetime.now().isoformat()}] ✅ Volatilidad 15 min {asset_label} del {target_day} = {vol_series.mean():.6f}")
    conn.close()

if __name__ == "__main__":
    main()
