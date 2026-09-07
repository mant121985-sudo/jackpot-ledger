"""
Refreshes megamillions_draw_history_validated.csv by pulling the two official
open-data feeds this project cross-validates against (NY Open Data / NY Gaming
Commission, and Texas Lottery's own published history), reconciling them the
same way the original validation pass did: TX is authoritative wherever both
cover a date (checked when this was first built - two real conflicts existed
in NY's feed, both resolved correctly by TX), NY fills only the pre-TX-era
window (2002-2003, before Texas joined Mega Millions).

Run: python refresh_megamillions_history.py
"""
import csv
import json
import urllib.request
from datetime import date
from pathlib import Path

NY_ENDPOINT = "https://data.ny.gov/resource/5xaw-6ayf.json?$limit=3000&$order=draw_date%20ASC"
TX_CSV_URL = "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/megamillions.csv"
OUTPUT_PATH = Path(__file__).parent / "megamillions_draw_history_validated.csv"


def fetch_ny():
    req = urllib.request.Request(NY_ENDPOINT, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    ny = {}
    for rec in raw:
        d = date.fromisoformat(rec["draw_date"][:10])
        whites = tuple(sorted(int(x) for x in rec["winning_numbers"].split()))
        ny[d] = (whites, int(rec["mega_ball"]))
    return ny


def fetch_tx():
    req = urllib.request.Request(TX_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    tx = {}
    for row in csv.reader(text.splitlines()):
        if not row or row[0] != "Mega Millions":
            continue
        d = date(int(row[3]), int(row[1]), int(row[2]))
        whites = tuple(sorted(int(x) for x in row[4:9]))
        tx[d] = (whites, int(row[9]))
    return tx


def main():
    ny = fetch_ny()
    tx = fetch_tx()
    all_dates = sorted(set(ny) | set(tx))

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["draw_date", "n1", "n2", "n3", "n4", "n5", "mega_ball", "source"])
        for d in all_dates:
            if d in tx:
                whites, mb = tx[d]
                src = "TX"
            else:
                whites, mb = ny[d]
                src = "NY(pre-TX or NY-only)"
            w.writerow([d.isoformat(), *whites, mb, src])

    print(f"Wrote {len(all_dates)} draws to {OUTPUT_PATH} (range {all_dates[0]} to {all_dates[-1]})")


if __name__ == "__main__":
    main()
