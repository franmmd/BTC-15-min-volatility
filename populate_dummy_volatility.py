#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
populate_dummy_volatility.py

Copia los datos de la última fecha presente en la tabla vol_15m y los inserta
para los 6 días anteriores (generando un total de 7 días de datos).
"""
import sqlite3
from pathlib import Path
import datetime as dt

DB_PATH = Path.home() / ".openclaw" / "btc_volatility.sqlite"
TABLE   = "vol_15m"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
# Obtener la última fecha disponible
cur.execute(f"SELECT MAX(day) FROM {TABLE}")
row = cur.fetchone()
if not row or not row[0]:
    print("No hay datos en la tabla.")
    exit(0)
last_day = dt.datetime.strptime(row[0], "%Y-%m-%d").date()
# Obtener todas las filas de esa fecha
cur.execute(f"SELECT * FROM {TABLE} WHERE day = ?", (last_day.isoformat(),))
rows = cur.fetchall()
cols = [description[0] for description in cur.description]
import random
# Insertar copias para los 6 días anteriores
for i in range(1, 7):
    new_day = (last_day - dt.timedelta(days=i)).isoformat()
    for r in rows:
        # r = (day, asset, v0..v95, computed_at)
        new_row = list(r)
        new_row[0] = new_day
        # Aplicar ligera variación aleatoria a los valores v0‑v95 para simular diferencias diarias
        for idx in range(2, 2+96):  # índices de v0..v95 en la fila
            if new_row[idx] is not None:
                factor = random.uniform(0.95, 1.05)  # ±5 %
                new_row[idx] = round(float(new_row[idx]) * factor, 6)
        new_row[-1] = dt.datetime.utcnow().isoformat()
        placeholders = ", ".join(["?" for _ in new_row])
        sql = f"INSERT OR REPLACE INTO {TABLE} VALUES ({placeholders})"
        cur.execute(sql, new_row)

# ...
conn.commit()
print(f"Datos duplicados para los 6 días anteriores a {last_day.isoformat()}.")
conn.close()
