"""
Single source of truth for both games' GameConfig objects, shared by
build_dashboard.py and update_picks_log.py so they can never drift apart -
if a tier value or era-start date changed in only one of them, the picks log
would silently score against the wrong prize table.
"""
from datetime import date
from pathlib import Path

from lottery_common import GameConfig, Tier

HERE = Path(__file__).parent

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
