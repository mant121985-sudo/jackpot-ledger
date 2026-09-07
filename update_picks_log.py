"""
Maintains picks_log.csv - the append-only record connecting each drawing's
emailed/displayed combo picks to what the numbers actually turned out to be,
once known.

Ten of the eleven tracked strategies get NOTHING fed back to them here - the
120-minute deep-search validation already proved that reading past outcomes
back into pick generation (that's literally what "hot numbers" is) carries no
real edge on an independent random draw, and this log's main job is to keep
proving that empirically over time with real results.

The eleventh, "adaptive feedback (own hit history)", is the deliberate
exception - and it tracks the METHOD, not the numbers. Each of the other ten
strategies' own real hit rate is ranked from picks_log.csv's resolved rows,
and this strategy simply becomes a clone of whichever one currently has the
best track record for that game (see compute_best_strategy below and
strat_adaptive_feedback in lottery_common.py). It is tracked on exactly equal
footing with the other ten, never singled out or favored in the dashboard/
email - specifically so its real performance keeps getting checked against
the others instead of just asserted to work or not work once.

Three jobs, run in order:
  1. RESOLVE - any "pending" row whose drawing has now happened (its date
     appears in the refreshed CSV) gets scored against the real result and
     flipped to "resolved".
  2. RANK METHODS - from all resolved rows so far, per game, find which of
     the ten base strategies currently has the best real hit rate.
  3. GENERATE - if there's no pending row yet for a game's next drawing,
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
from lottery_common import load_draws, next_draw_picks, score_pick, set_feedback_best_strategy

ADAPTIVE_STRATEGY_NAME = "adaptive feedback (own hit history)"

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


def compute_best_strategy(rows, game_name):
    """Rank the ten BASE strategies (excluding adaptive feedback itself, to
    avoid a self-referential loop) by their own resolved hit rate so far for
    this game, tiebreaking on total prize. Returns the current leader's name,
    or None if there isn't any resolved history yet to rank."""
    stats = {}
    for row in rows:
        if row["game"] != game_name or row["status"] != "resolved":
            continue
        name = row["strategy"]
        if name == ADAPTIVE_STRATEGY_NAME:
            continue
        s = stats.setdefault(name, {"n": 0, "hits": 0, "prize": 0})
        s["n"] += 1
        if row["tier"]:
            s["hits"] += 1
            s["prize"] += int(row["prize"]) if row["prize"] else 0
    if not stats:
        return None
    ranked = sorted(stats.items(), key=lambda kv: (kv[1]["hits"] / kv[1]["n"], kv[1]["prize"]), reverse=True)
    return ranked[0][0]


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

    mm_best = compute_best_strategy(rows, MM_CFG.name)
    pb_best = compute_best_strategy(rows, PB_CFG.name)
    if mm_best:
        set_feedback_best_strategy(MM_CFG.name, mm_best)
    if pb_best:
        set_feedback_best_strategy(PB_CFG.name, pb_best)

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
    print(f"  Adaptive feedback currently following: MM={mm_best or '(none yet, falls back to random)'}, "
          f"PB={pb_best or '(none yet, falls back to random)'}")


if __name__ == "__main__":
    main()
