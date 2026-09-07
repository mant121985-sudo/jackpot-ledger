"""
Orchestrator for the daily Jackpot Ledger refresh. Pure local file processing -
no network calls of its own, so it runs anywhere, including a network-restricted
sandbox. Produces dashboard_output.html, a complete, ready-to-publish page with
every placeholder in dashboard_template.html filled from already-fetched data.

This intentionally does NOT hit the network itself. The two draw-history CSVs
and live_data_cache.json are expected to already be fresh on disk - fetched by
fetch_live_data.py + refresh_megamillions_history.py + refresh_powerball_history.py,
which need real internet access and are meant to run somewhere that has it (a
GitHub Actions workflow in this repo, see .github/workflows/refresh.yml), not
inside whatever environment runs this script.

Steps:
  1. Load live jackpot/EV/last-draw data from live_data_cache.json.
  2. Read this drawing's already-locked-in combo picks from picks_log.csv
     (written by update_picks_log.py - never regenerated here, so re-running
     this script can't produce different numbers for the same drawing).
  3. Compute the running track-record tally from picks_log.csv's resolved rows.
  4. Fill dashboard_template.html and write dashboard_output.html + email_body.txt.

Run: python build_dashboard.py
"""
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import megamillions_live_ev as mm
import powerball_live_ev as pb
from game_configs import MM_CFG, PB_CFG, MM_ERA_START, PB_ERA_START

VALIDATION_DATE = "2026-09-07"  # date of the one-time 120-minute deep-search run
PICKS_LOG_PATH = HERE / "picks_log.csv"


def load_picks_for_drawing(game_name, drawing_date):
    """Read this drawing's already-generated picks from picks_log.csv - never
    regenerates them, so the same drawing always shows the same numbers."""
    if not PICKS_LOG_PATH.exists():
        raise RuntimeError(f"{PICKS_LOG_PATH} not found - run update_picks_log.py first.")
    picks = {}
    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["game"] == game_name and row["drawing_date"] == str(drawing_date):
                whites = tuple(int(row[f"n{i}"]) for i in range(1, 6))
                picks[row["strategy"]] = (whites, int(row["special"]))
    if not picks:
        raise RuntimeError(
            f"No picks logged for {game_name} drawing {drawing_date} - "
            f"run update_picks_log.py first."
        )
    return picks


def format_track_record(t, special_name):
    if t["n"] == 0:
        return "No drawings resolved yet — check back after the next drawing."
    win_rate = t["hits"] / t["n"] * 100
    line = (f"{t['n']} picks tracked across resolved drawings · {t['hits']} hit a prize tier "
            f"({win_rate:.1f}%) · ${t['cost']:,} hypothetically spent, ${t['prize']:,} hypothetically won "
            f"(net ${t['prize']-t['cost']:,})")
    if t["best_tier"]:
        tier, prize, ddate, strategy = t["best_tier"]
        line += f". Best result so far: {tier} (${prize:,}) on {ddate} via \"{strategy}\"."
    return line


def track_record(game_name, ticket_price):
    """Aggregate every resolved row for this game into a running tally."""
    if not PICKS_LOG_PATH.exists():
        return {"n": 0, "hits": 0, "cost": 0, "prize": 0, "best_tier": None}
    n = hits = cost = prize = 0
    best_tier = None
    best_prize = -1
    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["game"] != game_name or row["status"] != "resolved":
                continue
            n += 1
            cost += ticket_price
            row_prize = int(row["prize"]) if row["prize"] else 0
            prize += row_prize
            if row["tier"]:
                hits += 1
                if row_prize > best_prize:
                    best_prize = row_prize
                    best_tier = (row["tier"], row_prize, row["drawing_date"], row["strategy"])
    return {"n": n, "hits": hits, "cost": cost, "prize": prize, "best_tier": best_tier}


def load_cache():
    cache_path = HERE / "live_data_cache.json"
    if not cache_path.exists():
        raise RuntimeError(
            f"{cache_path} not found. This script only reads already-fetched data - "
            f"run fetch_live_data.py first (it needs real internet access)."
        )
    return json.loads(cache_path.read_text(encoding="utf-8"))


def money(v):
    return f"${v:,.0f}"


def money_short(v):
    return f"${v/1_000_000:.1f}M"


def balls_html(whites, special, small=True):
    cls = "ball small" if small else "ball"
    spans = "".join(f'<span class="{cls}">{n:02d}</span>' for n in whites)
    spans += f'<span class="{cls} special">{special:02d}</span>'
    return spans


def combos_js(picks):
    rows = [{"s": name, "w": list(w), "sp": sp} for name, (w, sp) in picks.items()]
    return json.dumps(rows)


def combos_text(picks, special_name):
    lines = []
    for name, (whites, sp) in picks.items():
        ball_str = " ".join(f"{n:02d}" for n in whites)
        lines.append(f"  {name:<32} {ball_str}  +  {special_name} {sp:02d}")
    return "\n".join(lines)


DASHBOARD_URL = "https://claude.ai/code/artifact/77e2ecf7-3a91-44b0-9015-0a1ca7f122b3"

EMAIL_TEMPLATE = """Jackpot Ledger - daily numbers, {refresh_date}

MEGA MILLIONS
Next drawing: {mm_next_draw}
Jackpot: {mm_jackpot} annuity / {mm_cash} cash
EV per $5 ticket: {mm_ev}  (RTP {mm_rtp})
Last drawing ({mm_last_date}): {mm_last_balls}

10 combos for the next drawing (one per tested strategy - locked in once generated,
never regenerated, so these are the exact numbers being tracked against the result):
{mm_combo_lines}

Track record so far: {mm_track_record}

POWERBALL
Next drawing: {pb_next_draw}
Jackpot: {pb_jackpot} annuity / {pb_cash} cash
EV per $2 ticket: {pb_ev}  (RTP {pb_rtp})
Last drawing ({pb_last_date}): {pb_last_balls}

10 combos for the next drawing (one per tested strategy - locked in once generated,
never regenerated, so these are the exact numbers being tracked against the result):
{pb_combo_lines}

Track record so far: {pb_track_record}

---
Straight talk: a 120-minute, million-plus-trial validation run found that NONE of these
strategies beat plain random number selection on a fair lottery draw - mathematically
expected, and confirmed empirically. These 10 combos are provided for variety/entertainment
only; every one of them has identical odds to any other 5-number pick. This is not a tip,
a prediction, or advice to play. The track record above is tracked for transparency only -
resolved outcomes are never fed back into how future picks are generated, because on an
independent random draw there is nothing real to learn from a past hit or miss.

Full dashboard (live, refreshed daily): {dashboard_url}
"""


def build_email_body(values, mm_picks, pb_picks):
    return EMAIL_TEMPLATE.format(
        refresh_date=values["__REFRESH_DATE__"],
        mm_next_draw=values["__MM_NEXT_DRAW__"],
        mm_jackpot=values["__MM_JACKPOT__"],
        mm_cash=values["__MM_CASH__"],
        mm_ev=values["__MM_EV__"],
        mm_rtp=values["__MM_RTP__"],
        mm_last_date=values["__MM_LAST_DRAW_DATE__"],
        mm_last_balls=values["_MM_LAST_DRAW_PLAIN"],
        mm_combo_lines=combos_text(mm_picks, "Mega Ball"),
        mm_track_record=values["__MM_TRACK_RECORD__"],
        pb_next_draw=values["__PB_NEXT_DRAW__"],
        pb_jackpot=values["__PB_JACKPOT__"],
        pb_cash=values["__PB_CASH__"],
        pb_ev=values["__PB_EV__"],
        pb_rtp=values["__PB_RTP__"],
        pb_last_date=values["__PB_LAST_DRAW_DATE__"],
        pb_last_balls=values["_PB_LAST_DRAW_PLAIN"],
        pb_combo_lines=combos_text(pb_picks, "Powerball"),
        pb_track_record=values["__PB_TRACK_RECORD__"],
        dashboard_url=DASHBOARD_URL,
    )


def main():
    cache = load_cache()
    mm_info = cache["megamillions"]
    pb_info = cache["powerball"]
    pb_last = pb_info["last_draw"]

    mm_floor = mm.non_jackpot_ev()
    mm_jp = 1 / mm.TOTAL_COMBOS
    mm_ev_ann = mm_floor + mm_jp * mm_info["next_jackpot_annuity"]
    mm_next = mm.next_draw_date(mm_info["last_draw_date"])
    mm_last_date_obj = datetime.strptime(mm_info["last_draw_date"], "%Y-%m-%d")

    pb_floor = pb.non_jackpot_ev()
    pb_jp = 1 / pb.TOTAL_COMBOS
    pb_ev_ann = pb_floor + pb_jp * pb_info["annuity"]
    pb_next = pb.next_draw_date(pb_last["date"])
    pb_last_date_obj = datetime.strptime(pb_last["date"], "%Y-%m-%d")

    mm_picks = load_picks_for_drawing(MM_CFG.name, mm_next)
    pb_picks = load_picks_for_drawing(PB_CFG.name, pb_next)

    mm_track = track_record(MM_CFG.name, MM_CFG.ticket_price)
    pb_track = track_record(PB_CFG.name, PB_CFG.ticket_price)

    mm_last_plain = " ".join(f"{n:02d}" for n in mm_info["last_draw_numbers"]) + f"  +  MB {mm_info['last_draw_mega_ball']:02d}"
    pb_last_plain = " ".join(f"{n:02d}" for n in pb_last["whites"]) + f"  +  PB {pb_last['powerball']:02d}"

    values = {
        "__MM_NEXT_DRAW__": f"{mm_next.strftime('%a %b')} {mm_next.day}, 11:00 PM ET" if mm_next else "TBD",
        "__MM_JACKPOT__": money(mm_info["next_jackpot_annuity"]),
        "__MM_CASH__": money_short(mm_info["next_jackpot_cash"]),
        "__MM_EV__": f"${mm_ev_ann:.2f}",
        "__MM_RTP__": f"{mm_ev_ann/5*100:.1f}%",
        "__MM_LAST_DRAW_DATE__": f"{mm_last_date_obj.strftime('%b')} {mm_last_date_obj.day}",
        "__MM_LAST_DRAW_BALLS__": balls_html(mm_info["last_draw_numbers"], mm_info["last_draw_mega_ball"]),

        "__PB_NEXT_DRAW__": f"{pb_next.strftime('%a %b')} {pb_next.day}, 10:59 PM ET" if pb_next else "TBD",
        "__PB_JACKPOT__": money(pb_info["annuity"]),
        "__PB_CASH__": money_short(pb_info["cash"]),
        "__PB_EV__": f"${pb_ev_ann:.2f}",
        "__PB_RTP__": f"{pb_ev_ann/2*100:.1f}%",
        "__PB_LAST_DRAW_DATE__": f"{pb_last_date_obj.strftime('%b')} {pb_last_date_obj.day}",
        "__PB_LAST_DRAW_BALLS__": balls_html(pb_last["whites"], pb_last["powerball"]),

        "__MM_COMBOS_JS__": combos_js(mm_picks),
        "__PB_COMBOS_JS__": combos_js(pb_picks),

        "__VALIDATION_DATE__": VALIDATION_DATE,
        "__REFRESH_DATE__": datetime.now(timezone.utc).strftime("%Y-%m-%d"),

        "__MM_TRACK_RECORD__": format_track_record(mm_track, "Mega Ball"),
        "__PB_TRACK_RECORD__": format_track_record(pb_track, "Powerball"),

        "_MM_LAST_DRAW_PLAIN": mm_last_plain,
        "_PB_LAST_DRAW_PLAIN": pb_last_plain,
    }

    template = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    for token, val in values.items():
        if token.startswith("_MM_") or token.startswith("_PB_"):
            continue  # email-only values, not template placeholders
        if token not in template:
            raise RuntimeError(f"Template missing expected placeholder: {token}")
        template = template.replace(token, val)

    out_path = HERE / "dashboard_output.html"
    out_path.write_text(template, encoding="utf-8")
    print(f"Wrote {out_path}")

    email_path = HERE / "email_body.txt"
    email_path.write_text(build_email_body(values, mm_picks, pb_picks), encoding="utf-8")
    print(f"Wrote {email_path}")


if __name__ == "__main__":
    main()
