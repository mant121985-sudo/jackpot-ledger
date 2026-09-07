"""
Maintains picks_log.csv - the append-only record connecting each drawing's
emailed/displayed combo picks to what the numbers actually turned out to be,
once known.

This is NOT a feedback mechanism. Resolved outcomes are never read back into
pick generation - the whole 120-minute deep-search validation already proved
that doing so (that's literally what the "hot numbers" strategy is) carries
no real edge on an independent random draw. This log exists purely so the
dashboard can show an honest, ongoing running tally - ongoing real-world
confirmation of that finding, not an attempt to overturn it.

Two jobs, run in order:
  1. RESOLVE - any "pending" row whose drawing has now happened (its date
     appears in the refreshed CSV) gets scored against the real result and
     flipped to "resolved".
  2. GENERATE - if there's no pending row yet for a game's next drawing,
     generate one now, with a SEED DERIVED FROM THE DRAWING DATE (not
     seed=None) so the picks are fixed once and for all for that drawing -
     re-running this script (e.g. an accidental duplicate trigger) never
     produces a different set of numbers for the same drawing.

Needs the CSVs already refreshed (run after refresh_*.py). No network calls
of its own.

Run: python update_picks_log.py
"""
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import megamillions_live_ev as mm
import powerball_live_ev as pb
from game_configs import MM_CFG, PB_CFG, MM_ERA_START, PB_ERA_START
from lottery_common import load_draws, next_draw_picks, score_pick

LOG_PATH = HERE / "picks_log.csv"
FIELDS = ["game", "drawing_date", "generated_at", "strategy",
          "n1", "n2", "n3", "n4", "n5", "special",
          "status", "white_matches", "special_match", "tier", "prize"]


def load_log():
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_log(rows):
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def resolve_pending(rows, cfg, draws_by_date):
    resolved_count = 0
    for row in rows:
        if row["game"] != cfg.name or row["status"] != "pending":
            continue
        d = date.fromisoformat(row["drawing_date"])
        actual = draws_by_date.get(d)
        if actual is None:
            continue
        actual_whites, actual_special = actual
        pick_whites = tuple(int(row[f"n{i}"]) for i in range(1, 6))
        pick_special = int(row["special"])
        tier_name, prize, wm, sm = score_pick(cfg, pick_whites, pick_special, actual_whites, actual_special)
        row["status"] = "resolved"
        row["white_matches"] = str(wm)
        row["special_match"] = str(int(sm))
        row["tier"] = tier_name or ""
        row["prize"] = str(prize or 0)
        resolved_count += 1
    return resolved_count


def ensure_pending(rows, cfg, draws, next_date):
    if any(r["game"] == cfg.name and r["drawing_date"] == str(next_date) and r["status"] == "pending"
           for r in rows):
        return 0
    if any(r["game"] == cfg.name and r["drawing_date"] == str(next_date) for r in rows):
        return 0  # already resolved somehow (shouldn't happen for a future date) - don't duplicate
    seed = int(next_date.strftime("%Y%m%d"))
    picks = next_draw_picks(cfg, draws, seed=seed)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, (whites, special) in picks.items():
        rows.append({
            "game": cfg.name, "drawing_date": str(next_date), "generated_at": now,
            "strategy": name, "n1": whites[0], "n2": whites[1], "n3": whites[2],
            "n4": whites[3], "n5": whites[4], "special": special,
            "status": "pending", "white_matches": "", "special_match": "", "tier": "", "prize": "",
        })
    return len(picks)


def main():
    rows = load_log()

    mm_draws = load_draws(MM_CFG, since=MM_ERA_START)
    pb_draws = load_draws(PB_CFG, since=PB_ERA_START)
    mm_by_date = {d: (w, s) for d, w, s in mm_draws}
    pb_by_date = {d: (w, s) for d, w, s in pb_draws}

    mm_resolved = resolve_pending(rows, MM_CFG, mm_by_date)
    pb_resolved = resolve_pending(rows, PB_CFG, pb_by_date)

    mm_last_date = max(mm_by_date)
    pb_last_date = max(pb_by_date)
    mm_next = mm.next_draw_date(mm_last_date.isoformat())
    pb_next = pb.next_draw_date(pb_last_date.isoformat())

    mm_generated = ensure_pending(rows, MM_CFG, mm_draws, mm_next)
    pb_generated = ensure_pending(rows, PB_CFG, pb_draws, pb_next)

    save_log(rows)

    n_pending = sum(1 for r in rows if r["status"] == "pending")
    n_resolved = sum(1 for r in rows if r["status"] == "resolved")
    print(f"picks_log.csv: {len(rows)} rows total ({n_pending} pending, {n_resolved} resolved)")
    print(f"  Resolved this run: {mm_resolved} MM, {pb_resolved} PB")
    print(f"  Generated this run: {mm_generated} MM (for {mm_next}), {pb_generated} PB (for {pb_next})")


if __name__ == "__main__":
    main()
