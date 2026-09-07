"""
Shared engine for lottery draw-history backtesting.

Walks a real draw history forward in time and, at each drawing, builds each
candidate strategy's number pick using ONLY the draws strictly before it (no
lookahead), then scores that pick against what was actually drawn. This is
the same walk-forward discipline used for a real trading backtest.

The honest starting expectation: Powerball and Mega Millions draws are
independently and uniformly random (state-audited equipment/RNGs). Every
5-number white-ball combination is exactly as likely as any other, so no
function of past draws can carry information about the next one. This module
exists to verify that empirically against the real, validated draw history
rather than just assert it - if a strategy here ever shows a statistically
significant edge over the random baseline across a large sample, that is
worth a second look; a small, noisy edge on a few hundred/thousand draws is
not.
"""
from dataclasses import dataclass
from datetime import date
from collections import Counter
import csv
import random


@dataclass
class Tier:
    name: str
    white_match: int
    special_match: bool
    prize: int  # base prize, pre-multiplier


@dataclass
class GameConfig:
    name: str
    csv_path: str
    white_max: int
    white_count: int
    special_max: int
    special_col: str
    special_name: str
    ticket_price: int
    tiers: list  # non-jackpot Tier list


def load_draws(cfg: GameConfig, since: date = None):
    rows = []
    with open(cfg.csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row["draw_date"])
            whites = tuple(sorted(int(row[f"n{i}"]) for i in range(1, cfg.white_count + 1)))
            special = int(row[cfg.special_col])
            rows.append((d, whites, special))
    rows.sort(key=lambda r: r[0])
    if since:
        rows = [r for r in rows if r[0] >= since]
    return rows


def score_pick(cfg, pick_whites, pick_special, actual_whites, actual_special):
    white_match = len(set(pick_whites) & set(actual_whites))
    special_match = (pick_special == actual_special)
    if white_match == cfg.white_count and special_match:
        return "JACKPOT", None, white_match, special_match
    for t in cfg.tiers:
        if t.white_match == white_match and t.special_match == special_match:
            return t.name, t.prize, white_match, special_match
    return None, 0, white_match, special_match


def _white_freq(history):
    c = Counter()
    for _d, whites, _s in history:
        c.update(whites)
    return c


def _special_freq(history):
    c = Counter()
    for _d, _w, s in history:
        c[s] += 1
    return c


def strat_random(cfg, history, rng):
    whites = tuple(sorted(rng.sample(range(1, cfg.white_max + 1), cfg.white_count)))
    special = rng.randint(1, cfg.special_max)
    return whites, special


def strat_hot(cfg, history, rng):
    wc = _white_freq(history)
    if not wc:
        return strat_random(cfg, history, rng)
    whites = tuple(sorted(n for n, _ in sorted(wc.items(), key=lambda x: -x[1])[:cfg.white_count]))
    sc = _special_freq(history)
    special = max(sc, key=sc.get) if sc else rng.randint(1, cfg.special_max)
    return whites, special


def strat_cold(cfg, history, rng):
    wc = _white_freq(history)
    all_whites = {n: wc.get(n, 0) for n in range(1, cfg.white_max + 1)}
    whites = tuple(sorted(n for n, _ in sorted(all_whites.items(), key=lambda x: x[1])[:cfg.white_count]))
    sc = _special_freq(history)
    all_special = {n: sc.get(n, 0) for n in range(1, cfg.special_max + 1)}
    special = min(all_special, key=all_special.get) if all_special else rng.randint(1, cfg.special_max)
    return whites, special


def strat_weighted(cfg, history, rng):
    wc = _white_freq(history)
    pool = list(range(1, cfg.white_max + 1))
    weights = [wc.get(n, 0) + 1 for n in pool]
    picked = set()
    while len(picked) < cfg.white_count:
        n = rng.choices(pool, weights=weights, k=1)[0]
        picked.add(n)
    sc = _special_freq(history)
    special_pool = list(range(1, cfg.special_max + 1))
    special_weights = [sc.get(n, 0) + 1 for n in special_pool]
    special = rng.choices(special_pool, weights=special_weights, k=1)[0]
    return tuple(sorted(picked)), special


def strat_recency_hot(cfg, history, rng, window=26):
    recent = history[-window:] if len(history) > window else history
    return strat_hot(cfg, recent, rng)


def _rejection_sample(cfg, rng, predicate, max_tries=300):
    for _ in range(max_tries):
        whites = tuple(sorted(rng.sample(range(1, cfg.white_max + 1), cfg.white_count)))
        if predicate(whites):
            return whites
    return tuple(sorted(rng.sample(range(1, cfg.white_max + 1), cfg.white_count)))


def strat_sum_range(cfg, history, rng):
    sums = [sum(whites) for _d, whites, _s in history]
    if sums:
        mean = sum(sums) / len(sums)
        var = sum((s - mean) ** 2 for s in sums) / len(sums)
        std = var ** 0.5
        lo, hi = mean - 0.5 * std, mean + 0.5 * std
    else:
        lo, hi = 0, cfg.white_max * cfg.white_count
    whites = _rejection_sample(cfg, rng, lambda w: lo <= sum(w) <= hi)
    special = rng.randint(1, cfg.special_max)
    return whites, special


def strat_odd_even_balance(cfg, history, rng):
    if history:
        odd_counts = Counter(sum(1 for n in whites if n % 2 == 1) for _d, whites, _s in history)
        target_odd = odd_counts.most_common(1)[0][0]
    else:
        target_odd = cfg.white_count // 2
    whites = _rejection_sample(cfg, rng, lambda w: sum(1 for n in w if n % 2 == 1) == target_odd)
    special = rng.randint(1, cfg.special_max)
    return whites, special


def strat_high_low_balance(cfg, history, rng):
    mid = cfg.white_max / 2
    if history:
        low_counts = Counter(sum(1 for n in whites if n <= mid) for _d, whites, _s in history)
        target_low = low_counts.most_common(1)[0][0]
    else:
        target_low = cfg.white_count // 2
    whites = _rejection_sample(cfg, rng, lambda w: sum(1 for n in w if n <= mid) == target_low)
    special = rng.randint(1, cfg.special_max)
    return whites, special


def strat_no_consecutive(cfg, history, rng):
    def no_consec(w):
        s = sorted(w)
        return all(s[i + 1] - s[i] > 1 for i in range(len(s) - 1))
    whites = _rejection_sample(cfg, rng, no_consec)
    special = rng.randint(1, cfg.special_max)
    return whites, special


def strat_pair_frequency(cfg, history, rng):
    pair_counts = Counter()
    for _d, whites, _s in history:
        w = sorted(whites)
        for i in range(len(w)):
            for j in range(i + 1, len(w)):
                pair_counts[(w[i], w[j])] += 1
    if not pair_counts:
        return strat_random(cfg, history, rng)
    scores = Counter()
    for (a, b), c in pair_counts.items():
        scores[a] += c
        scores[b] += c
    ranked = [n for n, _ in scores.most_common()]
    whites = set()
    for n in ranked:
        if len(whites) >= cfg.white_count:
            break
        whites.add(n)
    while len(whites) < cfg.white_count:
        whites.add(rng.randint(1, cfg.white_max))
    sc = _special_freq(history)
    special = max(sc, key=sc.get) if sc else rng.randint(1, cfg.special_max)
    return tuple(sorted(whites)), special


STRATEGIES = {
    "random (quick-pick baseline)": strat_random,
    "hot numbers (full history)": strat_hot,
    "hot numbers (last 26 draws)": strat_recency_hot,
    "cold / overdue numbers": strat_cold,
    "frequency-weighted": strat_weighted,
    "sum-range targeting": strat_sum_range,
    "odd/even balance": strat_odd_even_balance,
    "high/low balance": strat_high_low_balance,
    "no consecutive numbers": strat_no_consecutive,
    "pair co-occurrence": strat_pair_frequency,
}


def backtest(cfg: GameConfig, draws, min_history=30, seed=42):
    rng = random.Random(seed)
    results = {name: {"white_matches": Counter(), "special_hits": 0, "tier_hits": Counter(),
                       "total_prize": 0, "n": 0} for name in STRATEGIES}
    for i in range(min_history, len(draws)):
        history = draws[:i]
        _d, actual_whites, actual_special = draws[i]
        for name, fn in STRATEGIES.items():
            whites, special = fn(cfg, history, rng)
            tier_name, prize, wm, sm = score_pick(cfg, whites, special, actual_whites, actual_special)
            r = results[name]
            r["white_matches"][wm] += 1
            r["special_hits"] += int(sm)
            if tier_name:
                r["tier_hits"][tier_name] += 1
                r["total_prize"] += (prize or 0)
            r["n"] += 1
    return results


def next_draw_picks(cfg, draws, seed=None):
    rng = random.Random(seed)
    return {name: fn(cfg, draws, rng) for name, fn in STRATEGIES.items()}
