"""
Pulls viewer-submitted entries (from the dashboard's "Add Your Own" box) into
the pipeline. Reads submissions_raw.json - written by the daily routine via
the Artifact tool's read_db action (this script has no network/Artifact
access itself, consistent with build_dashboard.py staying 100% offline) -
normalized to:
  {
    "pick_submissions": [{"id","game","whites":[...],"special","name",
                           "raw_text","submitted_at"}, ...],
    "feedback_submissions": [{"id","text","name","submitted_at"}, ...]
  }

PICKS: validated against the target game's real matrix, then appended to
picks_log.csv as a new pending row for that game's CURRENT upcoming drawing -
tracked and resolved exactly like the 11 algorithmic strategies, tagged with
a "viewer pick: <name>" strategy label and a source_doc_id for idempotency
(a submission is only ever imported once, even if this runs again before the
drawing happens). Never overwrites or removes an already-generated pending
set - this is purely additive.

FEEDBACK: appended to the permanent feedback_log.csv (id, name, text,
submitted_at, first_seen_date), and any not seen in a previous run gets
written to new_feedback.txt for build_dashboard.py to fold into today's
email/dashboard.

If submissions_raw.json doesn't exist (no read_db data provided this run) or
is empty, this exits cleanly with nothing to do - a normal, expected state on
most days.

Run: python import_submissions.py
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
from game_configs import MM_CFG, PB_CFG

RAW_PATH = HERE / "submissions_raw.json"
PICKS_LOG_PATH = HERE / "picks_log.csv"
FEEDBACK_LOG_PATH = HERE / "feedback_log.csv"
NEW_FEEDBACK_PATH = HERE / "new_feedback.txt"
PICKS_FIELDS = ["game", "drawing_date", "generated_at", "strategy",
                "n1", "n2", "n3", "n4", "n5", "special",
                "status", "white_matches", "special_match", "tier", "prize",
                "source_doc_id"]
FEEDBACK_FIELDS = ["id", "name", "text", "submitted_at", "first_seen_date"]

GAMES = {MM_CFG.name: MM_CFG, PB_CFG.name: PB_CFG}


def load_picks_log():
    if not PICKS_LOG_PATH.exists():
        return []
    with open(PICKS_LOG_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row.setdefault("source_doc_id", "")
    return rows


def save_picks_log(rows):
    with open(PICKS_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PICKS_FIELDS)
        w.writeheader()
        w.writerows(rows)


def load_feedback_log():
    if not FEEDBACK_LOG_PATH.exists():
        return []
    with open(FEEDBACK_LOG_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_feedback_log(rows):
    with open(FEEDBACK_LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FEEDBACK_FIELDS)
        w.writeheader()
        w.writerows(rows)


def current_next_drawing_date(cfg):
    cache_path = HERE / "live_data_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    if cfg.name == MM_CFG.name:
        return mm.next_draw_date(cache["megamillions"]["last_draw_date"])
    else:
        return pb.next_draw_date(cache["powerball"]["last_draw"]["date"])


def import_picks(picks_log_rows):
    if not RAW_PATH.exists():
        return 0, 0
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    submissions = raw.get("pick_submissions", [])
    if not submissions:
        return 0, 0

    already_imported = {r["source_doc_id"] for r in picks_log_rows if r.get("source_doc_id")}
    next_date_cache = {}
    imported = 0
    rejected = 0

    for sub in submissions:
        doc_id = sub.get("id")
        if not doc_id or doc_id in already_imported:
            continue
        game_name = sub.get("game")
        cfg = GAMES.get(game_name)
        if cfg is None:
            rejected += 1
            continue
        whites = sub.get("whites")
        special = sub.get("special")
        if not isinstance(whites, list) or len(whites) != cfg.white_count:
            rejected += 1
            continue
        try:
            whites = [int(w) for w in whites]
            special = int(special)
        except (TypeError, ValueError):
            rejected += 1
            continue
        if len(set(whites)) != cfg.white_count:
            rejected += 1
            continue
        if not all(1 <= w <= cfg.white_max for w in whites):
            rejected += 1
            continue
        if not (1 <= special <= cfg.special_max):
            rejected += 1
            continue

        if game_name not in next_date_cache:
            next_date_cache[game_name] = current_next_drawing_date(cfg)
        drawing_date = next_date_cache[game_name]

        name = str(sub.get("name") or "Anonymous")[:40].strip() or "Anonymous"
        strategy_label = f"viewer pick ({name})"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        whites_sorted = sorted(whites)
        picks_log_rows.append({
            "game": game_name, "drawing_date": str(drawing_date), "generated_at": now,
            "strategy": strategy_label,
            "n1": whites_sorted[0], "n2": whites_sorted[1], "n3": whites_sorted[2],
            "n4": whites_sorted[3], "n5": whites_sorted[4], "special": special,
            "status": "pending", "white_matches": "", "special_match": "", "tier": "", "prize": "",
            "source_doc_id": doc_id,
        })
        already_imported.add(doc_id)
        imported += 1

    return imported, rejected


def import_feedback():
    feedback_log = load_feedback_log()
    seen_ids = {r["id"] for r in feedback_log}
    new_entries = []

    if RAW_PATH.exists():
        raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        for sub in raw.get("feedback_submissions", []):
            fid = sub.get("id")
            if not fid or fid in seen_ids:
                continue
            row = {
                "id": fid,
                "name": str(sub.get("name") or "Anonymous")[:40],
                "text": str(sub.get("text") or "")[:1000],
                "submitted_at": sub.get("submitted_at", ""),
                "first_seen_date": today,
            }
            feedback_log.append(row)
            new_entries.append(row)
            seen_ids.add(fid)

    if new_entries:
        save_feedback_log(feedback_log)

    if new_entries:
        lines = [f'  "{e["text"]}" - {e["name"]}' for e in new_entries]
        NEW_FEEDBACK_PATH.write_text("\n".join(lines), encoding="utf-8")
    else:
        NEW_FEEDBACK_PATH.write_text("", encoding="utf-8")

    return len(new_entries)


def main():
    picks_log_rows = load_picks_log()
    imported, rejected = import_picks(picks_log_rows)
    if imported:
        save_picks_log(picks_log_rows)
    n_new_feedback = import_feedback()

    print(f"Pick submissions: {imported} imported, {rejected} rejected (invalid game/range/count)")
    print(f"Feedback: {n_new_feedback} new entries this run")


if __name__ == "__main__":
    main()
