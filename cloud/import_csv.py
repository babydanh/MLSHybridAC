"""
Import CSV labeled data vào cloud database và trigger training.
"""
import csv
import json
import sqlite3
import time
import requests
from pathlib import Path

DB_PATH = "D:/Duancanhan/AC/cloud/data/vnac.db"
SERVER_URL = "http://127.0.0.1:8081"
API_KEY = "sk-60a56e0ff7826ca89eb0861ede9978c104968ae6a091711e2119462211d61a47"
ADMIN_KEY = "admin-test-key-123"

def import_csv(filepath: str, category: str, feature_count: int, label_idx: int = 1):
    """Import CSV vào database. Mặc định: col[0]=timestamp, col[1]=label, col[2:]=features"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    path = Path(filepath)
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"[CSV] {path.name}: {len(rows)} rows")

    count = 0
    for row in rows:
        timestamp = int(row.get("timestamp", time.time() * 1000)) / 1000.0
        label = float(row["label"])  # 0.0 hoặc 1.0
        # Lấy features từ f1 đến f{feature_count}
        features = [float(row[f"f{i}"]) for i in range(1, feature_count + 1)]

        conn.execute(
            """INSERT INTO training_samples
               (category, features_json, label, label_source, server_id, client_version,
                ping, tps, jitter, player_uuid, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (category, json.dumps(features), label, "whitebox_high", "csv-import",
             None, 50, 20.0, 0, None, timestamp),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"   [OK] Imported {count} {category} samples")
    return count

# ── Import ─────────────────────────────────────────────
print("=" * 50)
print("IMPORTING TRAINING DATA")
print("=" * 50)

aim_count = import_csv("C:/Users/GIGABYTE/Downloads/aim_samples.csv", "aim", 6)
session_count = import_csv("C:/Users/GIGABYTE/Downloads/session_samples.csv", "session", 8)

total = aim_count + session_count
print(f"\nTotal: {total} samples")
print(f"   Aim: {aim_count} (all cheat=1.0)")
print(f"   Session: {session_count} (all cheat=1.0)")
print(f"   [WARN] No legit data (label=0.0) — model will be biased")

# ── Kiểm tra ──────────────────────────────────────────
print("\n[DB] Checking database...")
conn = sqlite3.connect(DB_PATH)
for cat in ["aim", "session"]:
    row = conn.execute(
        "SELECT label, COUNT(*) as cnt FROM training_samples WHERE category=? GROUP BY label",
        (cat,)
    ).fetchall()
    print(f"   {cat}: {dict(row)}")
conn.close()

# ── Xác nhận với user ─────────────────────────────────
answer = input("\nTrain model now? (y/N): ")
if answer.lower() != "y":
    print("Bỏ qua training.")
    exit(0)

# ── Trigger train ─────────────────────────────────────
print("\n[Train] Triggering training...")
for cat in ["aim", "session"]:
    resp = requests.post(
        f"{SERVER_URL}/v1/train/trigger",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        json={"category": cat},
    )
    print(f"   {cat}: {resp.json()}")

print("\nDone! Check model files in cloud/data/models/")
