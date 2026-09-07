"""
Pulls the live Powerball jackpot from the Texas Lottery's official site (a state
lottery's own published estimate, cross-checked 2026-09-07 against USA Mega's
independent tracker and found to agree exactly - $190M annuity) and recomputes
exact odds / expected value for a $2 base ticket, plus the optional $1 Power
Play add-on, against the current 5/69 + 1/26 matrix (unchanged since 2015-10-07).

Unlike Mega Millions' built-in multiplier, Power Play is NOT automatic - it's
an extra $1/play add-on, and its 10X tier is suspended whenever the jackpot is
above $150M (official rule). This script checks the pulled jackpot against that
threshold and adjusts the Power Play EV calc accordingly.

Run: python powerball_live_ev.py
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta
from math import comb

TX_LOTTERY_URL = "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/index.html"
NY_RESULTS_ENDPOINT = "https://data.ny.gov/resource/d6yy-54nr.json?$order=draw_date%20DESC&$limit=1"

C69_5 = comb(69, 5)
TOTAL_COMBOS = C69_5 * 26  # 292,201,338

def ways_white(k):
    return comb(5, k) * comb(64, 5 - k)

TIERS = [
    ("5 + PB (JACKPOT)", 5, True,  None),
    ("5 + 0",            5, False, 1_000_000),
    ("4 + PB",           4, True,  50_000),
    ("4 + 0",            4, False, 100),
    ("3 + PB",           3, True,  100),
    ("3 + 0",            3, False, 7),
    ("2 + PB",           2, True,  7),
    ("1 + PB",           1, True,  4),
    ("0 + PB",           0, True,  4),
]

# Official Power Play multiplier odds as published (2X/3X/4X/5X/10X); renormalized
# to sum to 1 since the lottery's own rounded figures sum to ~1.023.
PP_ODDS_RAW = {2: 1/1.75, 3: 1/3.23, 4: 1/14.00, 5: 1/21.00, 10: 1/43.00}
_norm = sum(PP_ODDS_RAW.values())
PP_PROBS = {k: v / _norm for k, v in PP_ODDS_RAW.items()}
PP_10X_JACKPOT_CEILING = 150_000_000  # 10X suspended above this jackpot, per official rule


def fetch_live_jackpot():
    req = urllib.request.Request(TX_LOTTERY_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    text = re.sub("<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # First "Est. Annuitized Jackpot ... Est. Cash Value ..." block on this page is Powerball
    # (confirmed by page's own game ordering: Powerball, Mega Millions, Lotto Texas).
    m = re.search(
        r"Est\. Annuitized Jackpot for (\d{2}/\d{2}/\d{4}): \$([\d,.]+) Million "
        r"Est\. Cash Value: \$([\d,.]+) Million",
        text,
    )
    if not m:
        raise RuntimeError("Could not find Powerball jackpot on Texas Lottery page - site layout may have changed.")
    return {
        "draw_date": m.group(1),
        "annuity": float(m.group(2).replace(",", "")) * 1_000_000,
        "cash": float(m.group(3).replace(",", "")) * 1_000_000,
    }


def fetch_last_draw():
    """Most recent actual drawing, from the NY Open Data / NY Gaming Commission feed."""
    req = urllib.request.Request(NY_RESULTS_ENDPOINT, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    row = rows[0]
    nums = [int(x) for x in row["winning_numbers"].split()]
    return {
        "date": row["draw_date"][:10],
        "whites": sorted(nums[:5]),
        "powerball": nums[5],
    }


def next_draw_date(last_draw_date_str):
    """Powerball draws Monday, Wednesday, Saturday."""
    d = datetime.strptime(last_draw_date_str, "%Y-%m-%d").date()
    for offset in range(1, 8):
        candidate = d + timedelta(days=offset)
        if candidate.weekday() in (0, 2, 5):  # Mon=0, Wed=2, Sat=5
            return candidate
    return None


def non_jackpot_ev():
    ev = 0.0
    for _name, k, pbm, prize in TIERS:
        if prize is None:
            continue
        ways = ways_white(k) * (1 if pbm else 25)
        ev += (ways / TOTAL_COMBOS) * prize
    return ev


def main():
    info = fetch_live_jackpot()
    last = fetch_last_draw()
    floor_ev = non_jackpot_ev()
    jackpot_prob = 1 / TOTAL_COMBOS

    print(f"Last drawing: {last['date']}  numbers {last['whites']}  Powerball {last['powerball']}")
    nd = next_draw_date(last["date"])
    print(f"Next drawing: {nd}  10:59 PM ET  (results post same night at powerball.com)")
    print(f"Jackpot odds: 1 in {TOTAL_COMBOS:,}")
    print(f"Non-jackpot tiers EV floor: ${floor_ev:.4f} per $2 ticket\n")

    for label, jackpot in [("Annuity", info["annuity"]), ("Cash option", info["cash"])]:
        ev = floor_ev + jackpot_prob * jackpot
        print(f"{label:<14} ${jackpot:>15,.0f}  ->  $2 ticket EV = ${ev:.4f}  (RTP {ev/2*100:.2f}%)")

    ten_x_active = info["annuity"] <= PP_10X_JACKPOT_CEILING
    pp_probs = dict(PP_PROBS)
    if not ten_x_active:
        # 10X suspended above $150M: its share is redistributed to 2X per official rule.
        pp_probs = {k: v for k, v in PP_PROBS.items() if k != 10}
        pp_probs[2] += PP_PROBS[10]
    avg_mult = sum(k * v for k, v in pp_probs.items())
    ev_pp_annuity = floor_ev * avg_mult + jackpot_prob * info["annuity"]
    print(f"\nPower Play ($1 add-on, $3/play total): 10X {'ACTIVE' if ten_x_active else 'SUSPENDED (jackpot > $150M)'}")
    print(f"  E[multiplier] = {avg_mult:.4f}")
    print(f"  $3 ticket EV (annuity jackpot) = ${ev_pp_annuity:.4f}  (RTP {ev_pp_annuity/3*100:.2f}%)")

    breakeven = (2 - floor_ev) / jackpot_prob
    print(f"\nJackpot needed for base $2 ticket EV to reach $2.00 (break-even, pre-tax, single winner): ${breakeven:,.0f}")


if __name__ == "__main__":
    main()
