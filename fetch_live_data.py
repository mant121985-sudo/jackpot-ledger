"""
Fetches live jackpot/EV/last-draw data for both games and caches it to
live_data_cache.json. Split out from build_dashboard.py so this is the ONLY
script that needs real internet access - it's meant to run somewhere with
open egress (GitHub Actions), while build_dashboard.py itself stays 100%
local/offline and can run anywhere, including a network-restricted sandbox.

Run: python fetch_live_data.py
"""
import json
from pathlib import Path

import megamillions_live_ev as mm
import powerball_live_ev as pb

HERE = Path(__file__).parent


def main():
    mm_info = mm.fetch_live_jackpot()
    pb_info = pb.fetch_live_jackpot()
    pb_last = pb.fetch_last_draw()

    cache = {
        "megamillions": mm_info,
        "powerball": {**pb_info, "last_draw": pb_last},
    }
    out_path = HERE / "live_data_cache.json"
    out_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
