"""
Orchestrator for the daily Jackpot Ledger refresh. Pure Python/curl - no LLM calls,
no tokens spent. Produces dashboard_output.html, a complete, ready-to-publish page
with every placeholder in dashboard_template.html filled from live data.

Steps:
  1. Refresh both draw-history CSVs from the two official feeds (cross-validated).
  2. Pull live jackpot/EV/last-draw data for both games.
  3. Generate one next-drawing combo per tested strategy, both games.
  4. Fill dashboard_template.html and write dashboard_output.html.

The calling agent's only remaining job is to publish dashboard_output.html to the
existing Artifact URL - no data logic should live in that step.

Run: python build_dashboard.py
"""
import json
import subprocess
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


def run_refresh():
    for script in ("refresh_megamillions_history.py", "refresh_powerball_history.py"):
        result = subprocess.run([sys.executable, str(HERE / script)], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"{script} failed:\n{result.stdout}\n{result.stderr}")
        print(result.stdout.strip())


def money(v):
    return f"${v:,.0f}"


def money_short(v):
    return f"${v/1_000_000:.1f}M"


def balls_html(whites, special, small=True):
    cls = "ball small" if small else "ball"
    spans = "".join(f'<span class="{cls}">{n:02d}</span>' for n in whites)
    spans += f'<span class="{cls} special">{special:02d}</span>'
    return spans


def combos_js(cfg, draws):
    picks = next_draw_picks(cfg, draws, seed=None)
    rows = [{"s": name, "w": list(w), "sp": sp} for name, (w, sp) in picks.items()]
    return json.dumps(rows)


def main():
    run_refresh()

    mm_info = mm.fetch_live_jackpot()
    mm_floor = mm.non_jackpot_ev()
    mm_jp = 1 / mm.TOTAL_COMBOS
    mm_ev_ann = mm_floor + mm_jp * mm_info["next_jackpot_annuity"]
    mm_next = mm.next_draw_date(mm_info["last_draw_date"])
    mm_last_date_obj = datetime.strptime(mm_info["last_draw_date"], "%Y-%m-%d")

    pb_info = pb.fetch_live_jackpot()
    pb_last = pb.fetch_last_draw()
    pb_floor = pb.non_jackpot_ev()
    pb_jp = 1 / pb.TOTAL_COMBOS
    pb_ev_ann = pb_floor + pb_jp * pb_info["annuity"]
    pb_next = pb.next_draw_date(pb_last["date"])
    pb_last_date_obj = datetime.strptime(pb_last["date"], "%Y-%m-%d")

    mm_draws = load_draws(MM_CFG, since=MM_ERA_START)
    pb_draws = load_draws(PB_CFG, since=PB_ERA_START)

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

        "__MM_COMBOS_JS__": combos_js(MM_CFG, mm_draws),
        "__PB_COMBOS_JS__": combos_js(PB_CFG, pb_draws),

        "__VALIDATION_DATE__": VALIDATION_DATE,
        "__REFRESH_DATE__": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    template = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    for token, val in values.items():
        if token not in template:
            raise RuntimeError(f"Template missing expected placeholder: {token}")
        template = template.replace(token, val)

    out_path = HERE / "dashboard_output.html"
    out_path.write_text(template, encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
