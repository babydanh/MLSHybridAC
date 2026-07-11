"""
Import CSV labeled data into cloud database via HTTP API.
Safer than direct DB writes when server is running.
"""
import csv
import json
import time
import requests
from pathlib import Path

SERVER_URL = "http://127.0.0.1:8081"
API_KEY = "sk-60a56e0ff7826ca89eb0861ede9978c104968ae6a091711e2119462211d61a47"

def import_csv_via_api(filepath: str, category: str, feature_count: int):
    path = Path(filepath)
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"[CSV] {path.name}: {len(rows)} rows, sending to API...")

    count = 0
    errors = 0
    for row in rows:
        label = float(row["label"])
        features = [float(row[f"f{i}"]) for i in range(1, feature_count + 1)]

        payload = {
            "category": category,
            "features": features,
            "label": label,
            "label_source": "whitebox_high",
            "ping": 50,
            "tps": 20.0,
        }

        try:
            resp = requests.post(
                f"{SERVER_URL}/v1/training/sample",
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=5,
            )
            if resp.status_code == 200:
                count += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1

        if count % 200 == 0 and count > 0:
            print(f"   ... {count}/{len(rows)}")

    print(f"   [OK] Imported {count} {category} samples ({errors} errors)")
    return count


# --- Import ---
print("=" * 50)
print("IMPORTING TRAINING DATA VIA API")
print("=" * 50)

aim_count = import_csv_via_api("C:/Users/GIGABYTE/Downloads/aim_samples.csv", "aim", 6)
session_count = import_csv_via_api("C:/Users/GIGABYTE/Downloads/session_samples.csv", "session", 8)

total = aim_count + session_count
print(f"\nTotal: {total} samples")
print(f"   Aim: {aim_count} (all cheat=1.0)")
print(f"   Session: {session_count} (all cheat=1.0)")
print(f"   [WARN] No legit data (label=0.0) - model will be biased")
