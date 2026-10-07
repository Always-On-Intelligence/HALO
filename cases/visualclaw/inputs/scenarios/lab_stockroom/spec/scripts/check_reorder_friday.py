"""q6: docs/reorder_friday.json applies the sealed-only count and the par rule to four walkthrough items."""
from _rows import main

main("docs/reorder_friday.json", "item", [
    {"item": "200 uL tips", "on_hand": 4, "par": 3, "reorder": False},
    {"item": "Tris-HCl buffer pH 8.0", "on_hand": 0, "par": 1, "reorder": True},
    {"item": "Serological pipettes 10 mL", "on_hand": 6, "par": 5, "reorder": False},
    {"item": "Parafilm M", "on_hand": 1, "par": 2, "reorder": True},
])
