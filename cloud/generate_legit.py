"""
Generate synthetic legit data from existing cheat samples.
Adds noise to flip cheat → legit for testing training pipeline.
"""
import csv
import json
import random
import sqlite3
import requests
from pathlib import Path

SERVER_URL = "http://127.0.0.1:8081"
API_KEY = "sk-60a56e0ff7826ca89eb0861ede9978c104968ae6a091711e2119462211d61a47"
DB_PATH = "D:/Duancanhan/AC/cloud/data/vnac.db"

def generate_legit_and_import(category, feature_count):
    """Generate synthetic legit data by adding noise to cheat samples."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT features_json FROM training_samples WHERE category=? AND label=1.0",
        (category,)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"   No cheat samples for {category}")
        return

    cheat_features = [json.loads(r[0]) for r in rows]
    n_legit = min(len(cheat_features), 500)  # 500 legit samples

    count = 0
    for i in range(n_legit):
        cheat = cheat_features[i % len(cheat_features)]
        # Add noise to flip to legit behavior
        legit = [f + random.uniform(-0.3, 0.3) * (abs(f) + 0.1) for f in cheat]
        # Clamp reasonable ranges
        legit = [max(-10.0, min(10.0, v)) for v in legit]

        payload = {
            "category": category,
            "features": legit,
            "label": 0.0,
            "label_source": "synthetic_legit",
            "ping": random.randint(10, 100),
            "tps": round(random.uniform(19.5, 20.0), 1),
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
        except:
            pass

    print(f"   [OK] Generated {count} synthetic legit {category} samples")


# --- Main ---
print("=" * 50)
print("GENERATING SYNTHETIC LEGIT DATA")
print("=" * 50)

# Check current stats
conn = sqlite3.connect(DB_PATH)
for cat in ["aim", "session"]:
    row = conn.execute(
        "SELECT label, COUNT(*) FROM training_samples WHERE category=? GROUP BY label",
        (cat,)
    ).fetchall()
    print(f"  {cat} before: {dict(row)}")
conn.close()

generate_legit_and_import("aim", 6)
generate_legit_and_import("session", 8)

# Verify
conn = sqlite3.connect(DB_PATH)
for cat in ["aim", "session"]:
    row = conn.execute(
        "SELECT label, COUNT(*) FROM training_samples WHERE category=? GROUP BY label",
        (cat,)
    ).fetchall()
    print(f"  {cat} after: {dict(row)}")
conn.close()
