"""
Pulls the live Mega Millions jackpot straight from the official megamillions.com
data endpoint and recomputes exact odds / expected value for a $5 ticket against
the current 5/70 + 1/24 matrix (effective 2025-04-08).

Source of truth for the jackpot number: megamillions.com's own CMS service
(the same feed that drives the numbers shown on the site), not a third-party
aggregator. Prize table and multiplier distribution are the fixed, official
2025-rules structure (verified against Maryland Lottery's published table on
2026-09-07) and don't need to be re-fetched each run.

Run: python megamillions_live_ev.py
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta
from math import comb

OFFICIAL_ENDPOINT = "https://www.megamillions.com/cmspages/utilservice.asmx/GetLatestDrawData"

# Fixed game structure, current matrix (5 white 1-70, 1 Mega Ball 1-24), $5 base play.
C70_5 = comb(70, 5)
TOTAL_COMBOS = C70_5 * 24  # 290,472,336

def ways_white(k):
    return comb(5, k) * comb(65, 5 - k)

# (tier name, white-ball matches, mega-ball match required, base prize or None for jackpot)
TIERS = [
    ("5 + MB (JACKPOT)", 5, True,  None),
    ("5 + 0",            5, False, 1_000_000),
    ("4 + MB",           4, True,  10_000),
    ("4 + 0",            4, False, 500),
    ("3 + MB",           3, True,  200),
    ("3 + 0",            3, False, 10),
    ("2 + MB",           2, True,  10),
    ("1 + MB",           1, True,  7),
    ("0 + MB",           0, True,  5),
]

# Official built-in multiplier distribution (2x/3x/4x/5x/10x at 15/10/4/2/1 out of 32).
# Applies to every non-jackpot prize; E[multiplier] = (2*15+3*10+4*4+5*2+10*1)/32 = 3.0 exactly.
AVG_MULTIPLIER = 3.0


def fetch_live_jackpot():
    req = urllib.request.Request(OFFICIAL_ENDPOINT, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    # Response is an XML <string> wrapper around a JSON payload.
    match = re.search(r">(\{.*\})<", raw, re.S)
    payload = json.loads(match.group(1))
    j = payload["Jackpot"]
    d = payload["Drawing"]
    return {
        "last_draw_date": d["PlayDate"][:10],
        "last_draw_numbers": sorted([d["N1"], d["N2"], d["N3"], d["N4"], d["N5"]]),
        "last_draw_mega_ball": d["MBall"],
        "last_draw_winners": j["Winners"],
        "next_jackpot_annuity": j["NextPrizePool"],
        "next_jackpot_cash": j["NextCashValue"],
    }


def next_draw_date(last_draw_date_str):
    """Mega Millions draws Tuesday and Friday."""
    d = datetime.strptime(last_draw_date_str, "%Y-%m-%d").date()
    for offset in range(1, 8):
        candidate = d + timedelta(days=offset)
        if candidate.weekday() in (1, 4):  # Tue=1, Fri=4
            return candidate
    return None


def non_jackpot_ev():
    ev = 0.0
    for _name, k, mb_match, prize in TIERS:
        if prize is None:
            continue
        ways = ways_white(k) * (1 if mb_match else 23)
        prob = ways / TOTAL_COMBOS
        ev += prob * prize * AVG_MULTIPLIER
    return ev


def main():
    info = fetch_live_jackpot()
    floor_ev = non_jackpot_ev()
    jackpot_prob = 1 / TOTAL_COMBOS

    print(f"Last drawing: {info['last_draw_date']}  numbers {info['last_draw_numbers']} "
          f"MB {info['last_draw_mega_ball']}  (jackpot winners: {info['last_draw_winners']})")
    nd = next_draw_date(info["last_draw_date"])
    print(f"Next drawing: {nd}  11:00 PM ET  (results post same night at megamillions.com)")
    print(f"Jackpot odds: 1 in {TOTAL_COMBOS:,}")
    print(f"Non-jackpot tiers EV floor: ${floor_ev:.4f} per $5 ticket\n")

    for label, jackpot in [
        ("Next drawing - annuity", info["next_jackpot_annuity"]),
        ("Next drawing - cash option", info["next_jackpot_cash"]),
    ]:
        ev = floor_ev + jackpot_prob * jackpot
        print(f"{label:<28} ${jackpot:>15,.0f}  ->  EV/$5 ticket = ${ev:.4f}  (RTP {ev/5*100:.2f}%)")

    breakeven = (5 - floor_ev) / jackpot_prob
    print(f"\nJackpot needed for EV to reach $5.00 (break-even, pre-tax, single winner): ${breakeven:,.0f}")


if __name__ == "__main__":
    main()
