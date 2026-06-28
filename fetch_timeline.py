import json
import os
import shutil
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE = Path(__file__).parent

def backup(path: Path):
    if not path.exists():
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = BASE / "backups" / f"{path.stem}_{ts}{path.suffix}"
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(path, dest)

api_key = os.getenv("UMA_MOE_API_KEY")

response = requests.get(
    "https://uma.moe/resources/current/banner_timeline.json.gz",
    headers={
        "User-Agent": "UmaCircleBot/1.7",
        "X-API-Key": api_key,
    },
)

response.raise_for_status()

data = response.json()

out = BASE / "timeline.json"
backup(out)
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Saved to {out}")
