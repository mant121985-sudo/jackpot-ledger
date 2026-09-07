"""
Historical replay validation. Runs the FULL current pipeline - all 11
strategies, including the dynamic adaptive-feedback leader-following
mechanism - against real past drawings in chronological order, exactly as
they will be encountered live: at each historical date, only draws strictly
before it are visible, picks get generated and scored against what actually
happened, and the adaptive-feedback leader is recomputed from the (growing)
result log before the next date's picks are made.

This is NOT the same as the hand-crafted single-row tests used earlier to
check the scoring code works - this replays the real 11-strategy system,
unmodified, across the ENTIRE available real history for both games, so the
adaptive-feedback mechanism actually gets to shift leaders over time exactly
as it would in production.

Writes nothing to the real picks_log.csv - fully isolated.

Run: python historical_replay_test.py
"""
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from game_configs import MM_CFG, PB_CFG, MM_ERA_START, PB_ERA_START
from lottery_common import load_draws, next_draw_picks, score_pick, set_feedback_best_strategy, STRATEGIES

ADAPTIVE = "adaptive feedback (own hit history)"


def theoretical_win_rate(cfg):
    total_combos = comb(cfg.white_max, cfg.white_count) * cfg.special_max
    hits = 0
    for t in cfg.tiers:
        ways = comb(cfg.white_count, t.white_match) * comb(cfg.white_max - cfg.white_count, cfg.white_count - t.white_match)
        ways *= 1 if t.special_match else (cfg.special_max - 1)
        hits += ways
    return hits / total_combos


def replay(cfg, draws, min_history=30):
    log = []  # resolved rows: {strategy, tier, prize}
    stats = {name: {"n": 0, "hits": 0, "prize": 0, "cost": 0} for name in STRATEGIES}
    leader_changes = []

    for i in range(min_history, len(draws)):
        history = draws[:i]
        actual_date, actual_whites, actual_special = draws[i]

        base_stats = {}
        for row in log:
            if row["strategy"] == ADAPTIVE:
                continue
            s = base_stats.setdefault(row["strategy"], {"n": 0, "hits": 0, "prize": 0})
            s["n"] += 1
            if row["tier"]:
                s["hits"] += 1
                s["prize"] += row["prize"]
        leader = None
        if base_stats:
            leader = sorted(base_stats.items(),
                             key=lambda kv: (kv[1]["hits"] / kv[1]["n"], kv[1]["prize"]), reverse=True)[0][0]
            set_feedback_best_strategy(cfg.name, leader)
        if leader_changes[-1:] != [leader]:
            leader_changes.append(leader)

        seed = int(actual_date.strftime("%Y%m%d"))
        picks = next_draw_picks(cfg, history, seed=seed)
        for name, (whites, special) in picks.items():
            tier_name, prize, wm, sm = score_pick(cfg, whites, special, actual_whites, actual_special)
            prize = prize or 0
            log.append({"strategy": name, "tier": tier_name, "prize": prize})
            s = stats[name]
            s["n"] += 1
            s["cost"] += cfg.ticket_price
            if tier_name:
                s["hits"] += 1
                s["prize"] += prize

    return stats, leader_changes


def main():
    mm_draws = load_draws(MM_CFG, since=MM_ERA_START)
    pb_draws = load_draws(PB_CFG, since=PB_ERA_START)

    for label, cfg, draws in [("Mega Millions", MM_CFG, mm_draws), ("Powerball", PB_CFG, pb_draws)]:
        print("=" * 78)
        print(f"{label}: replaying {len(draws)} real historical drawings (current matrix era)")
        print("=" * 78)
        theo = theoretical_win_rate(cfg)
        print(f"Theoretical win-any-prize rate for ANY pick: {theo*100:.4f}%\n")

        stats, leader_changes = replay(cfg, draws)

        ranked = sorted(stats.items(), key=lambda kv: -(kv[1]["hits"] / kv[1]["n"]) if kv[1]["n"] else 0)
        print(f"{'Strategy':<35}{'n':>6}{'hits':>6}{'win %':>9}{'net $':>12}")
        for name, s in ranked:
            if s["n"] == 0:
                continue
            win_rate = s["hits"] / s["n"] * 100
            net = s["prize"] - s["cost"]
            flag = "  <-- adaptive feedback" if name == ADAPTIVE else ""
            print(f"{name:<35}{s['n']:>6}{s['hits']:>6}{win_rate:>8.2f}%{net:>12,}{flag}")

        print(f"\nAdaptive feedback's leader changed {len(leader_changes)-1} times over the replay "
              f"(started at None/random, ended following \"{leader_changes[-1]}\").")
        print()


if __name__ == "__main__":
    main()
