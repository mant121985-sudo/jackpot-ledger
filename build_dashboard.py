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
  2. Generate one next-drawing combo per tested strategy, both games, from the
     (already-fresh) draw-history CSVs.
  3. Fill dashboard_template.html and write dashboard_output.html + email_body.txt.

Run: python build_dashboard.py
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import megamillions_live_ev as mm
import powerball_live_ev as pb
from lottery_common import GameConfig, Tier, load_draws, next_draw_picks

MM_CFG = GameConfig(
    name="Mega Millions", csv_path=str(HERE / "megamillions_draw_history_validated.csv"),
    white_max=70, white_count=5, special_max=24, special_col="mega_ball",
    special_name="Mega Ball", ticket_price=5,
    tiers=[Tier("5+0", 5, False, 1_000_000), Tier("4+MB", 4, True, 10_000),
           Tier("4+0", 4, False, 500), Tier("3+MB", 3, True, 200),
           Tier("3+0", 3, False, 10), Tier("2+MB", 2, True, 10),
           Tier("1+MB", 1, True, 7), Tier("0+MB", 0, True, 5)],
)
PB_CFG = GameConfig(
    name="Powerball", csv_path=str(HERE / "powerball_draw_history_validated.csv"),
    white_max=69, white_count=5, special_max=26, special_col="powerball",
    special_name="Powerball", ticket_price=2,
    tiers=[Tier("5+0", 5, False, 1_000_000), Tier("4+PB", 4, True, 50_000),
           Tier("4+0", 4, False, 100), Tier("3+PB", 3, True, 100),
           Tier("3+0", 3, False, 7), Tier("2+PB", 2, True, 7),
           Tier("1+PB", 1, True, 4), Tier("0+PB", 0, True, 4)],
)
MM_ERA_START = date(2025, 4, 8)
PB_ERA_START = date(2015, 10, 7)
VALIDATION_DATE = "2026-09-07"  # date of the one-time 120-minute deep-search run


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

10 combos for the next drawing (one per tested strategy):
{mm_combo_lines}

POWERBALL
Next drawing: {pb_next_draw}
Jackpot: {pb_jackpot} annuity / {pb_cash} cash
EV per $2 ticket: {pb_ev}  (RTP {pb_rtp})
Last drawing ({pb_last_date}): {pb_last_balls}

10 combos for the next drawing (one per tested strategy):
{pb_combo_lines}

---
Straight talk: a 120-minute, million-plus-trial validation run found that NONE of these
strategies beat plain random number selection on a fair lottery draw - mathematically
expected, and confirmed empirically. These 10 combos are provided for variety/entertainment
only; every one of them has identical odds to any other 5-number pick. This is not a tip,
a prediction, or advice to play.

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
        pb_next_draw=values["__PB_NEXT_DRAW__"],
        pb_jackpot=values["__PB_JACKPOT__"],
        pb_cash=values["__PB_CASH__"],
        pb_ev=values["__PB_EV__"],
        pb_rtp=values["__PB_RTP__"],
        pb_last_date=values["__PB_LAST_DRAW_DATE__"],
        pb_last_balls=values["_PB_LAST_DRAW_PLAIN"],
        pb_combo_lines=combos_text(pb_picks, "Powerball"),
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

    mm_draws = load_draws(MM_CFG, since=MM_ERA_START)
    pb_draws = load_draws(PB_CFG, since=PB_ERA_START)
    mm_picks = next_draw_picks(MM_CFG, mm_draws, seed=None)
    pb_picks = next_draw_picks(PB_CFG, pb_draws, seed=None)

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
