#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly_volatility_report.py

Genera un informe semanal (max‑media‑min) de volatilidad a 15 min
para los activos BTC, ETH, SOL y XMR y lo envía por Telegram.
"""

import os, sys, json, sqlite3, datetime as dt
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import tempfile
import numpy as np
import requests

# ----------------------------------------------------------------------
# Configuración
DB_PATH   = Path.home() / ".openclaw" / "btc_volatility.sqlite"
TABLE     = "vol_15m"                     # tabla que usamos en el script diario
ASSETS    = ["BTC", "ETH", "SOL", "XMR"] # activos a reportar
TELEGRAM_BOT_TOKEN = None                 # se cargará desde openclaw.json
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")  # debe estar en el entorno

# ----------------------------------------------------------------------
def load_bot_token() -> str:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        cfg = json.loads(cfg_path.read_text())
        return cfg["channels"]["telegram"]["botToken"]
    except Exception as e:
        print(f"❌ No se pudo leer el token del bot: {e}", file=sys.stderr)
        sys.exit(1)

def fetch_last_7_days_for_asset(conn: sqlite3.Connection, asset: str) -> pd.DataFrame:
    """Devuelve un DataFrame con hasta 7 filas del activo especificado, ordenadas por día descendente."""
    cur = conn.cursor()
    query = f"""
        SELECT day, asset, {', '.join([f'v{i}' for i in range(96)])}
        FROM {TABLE}
        WHERE asset = ?
        ORDER BY day DESC
        LIMIT 7;
    """
    cur.execute(query, (asset,))
    rows = cur.fetchall()
    cols = ["day", "asset"] + [f"v{i}" for i in range(96)]
    df = pd.DataFrame(rows, columns=cols)
    df["day"] = pd.to_datetime(df["day"])
    return df

def compute_stats(df_asset: pd.DataFrame) -> dict:
    vals = df_asset[[f"v{i}" for i in range(96)]].astype(float)
    return {"max": vals.max().tolist(), "mean": vals.mean().tolist(), "min": vals.min().tolist()}

def plot_asset(asset: str, stats: dict) -> str:
    x = np.arange(96)
    fig, ax = plt.subplots(figsize=(13, 5))
    # Máximo – rojo, línea gruesa, marcador triangular
    ax.plot(x, stats["max"], label="Máximo", color="#d33", linewidth=2, marker='^', markersize=5)
    # Media – azul, línea media, marcador circular
    ax.plot(x, stats["mean"], label="Media", color="#28a", linewidth=2, marker='o', markersize=5)
    # Mínimo – verde, línea fina, marcador cuadrado
    ax.plot(x, stats["min"], label="Mínimo", color="#3a3", linewidth=2, marker='s', markersize=5)
    ax.set_title(f"Volatilidad 15 min – {asset} (últimos 7 días)", fontsize=14)
    ax.set_xlabel("Tramo de 15 min (v0 … v95)", fontsize=12)
    ax.set_ylabel("Volatilidad (σ)", fontsize=12)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    # Etiquetas X cada 2 h (8 tramos)
    hours = [f"{(i*15)//60:02d}:{(i*15)%60:02d}" for i in range(0, 96, 8)]
    ax.set_xticks(range(0, 96, 8))
    ax.set_xticklabels(hours, rotation=45, ha="right")
    # Ajustar límites Y con margen para que los puntos no queden en el borde
    y_min = min(np.nanmin(stats["min"]), np.nanmin(stats["mean"]), np.nanmin(stats["max"]))
    y_max = max(np.nanmax(stats["min"]), np.nanmax(stats["mean"]), np.nanmax(stats["max"]))
    margin = (y_max - y_min) * 0.1 if y_max != y_min else 0.001
    ax.set_ylim(y_min - margin, y_max + margin)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        fig.savefig(tmp.name, bbox_inches="tight")
        path = tmp.name
    plt.close(fig)
    return path

def send_telegram_image(token: str, chat_id: str, caption: str, img_path: str):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    with open(img_path, "rb") as f:
        files = {"photo": f}
        r = requests.post(url, data=payload, files=files, timeout=10)
    r.raise_for_status()
    print("✅ Informe semanal enviado a Telegram")

def main():
    global TELEGRAM_BOT_TOKEN
    TELEGRAM_BOT_TOKEN = load_bot_token()
    if not CHAT_ID:
        print("❌ La variable de entorno TELEGRAM_CHAT_ID no está definida.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    for asset in ASSETS:
        df_asset = fetch_last_7_days_for_asset(conn, asset)
        if df_asset.empty:
            print(f"⚠️ No hay datos de {asset} en la última semana → se omite.")
            continue
        stats = compute_stats(df_asset)
        # DEBUG: imprimir valores de estadísticas
        print(f"DEBUG {asset} stats: max={stats['max'][:3]}..., mean={stats['mean'][:3]}..., min={stats['min'][:3]}...")
        img_path = plot_asset(asset, stats)
        caption = (
            f"*Informe semanal de volatilidad – {asset}*\n"
            f"Periodo: últimos 7 días ({df_asset['day'].min().date()} → {df_asset['day'].max().date()})\n"
            "Se grafican los valores **máximo**, **media** y **mínimo** por cada tramo de 15 min."
        )
        send_telegram_image(TELEGRAM_BOT_TOKEN, CHAT_ID, caption, img_path)
        try:
            os.remove(img_path)
        except Exception:
            pass
    conn.close()
if __name__ == "__main__":
    main()
