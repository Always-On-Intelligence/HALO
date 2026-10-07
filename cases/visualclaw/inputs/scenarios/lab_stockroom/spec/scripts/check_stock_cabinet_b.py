"""q3: docs/stock_cabinet_b.json holds sealed-only on-hand counts for the three cabinet B items, each cited."""
from _rows import main

main("docs/stock_cabinet_b.json", "item", [
    {"item": "Nitrile gloves size M", "on_hand": 3},
    {"item": "10 uL filter tips", "on_hand": 1},
    {"item": "1.5 mL microcentrifuge tubes", "on_hand": 2},
], cite_key="evidence")
