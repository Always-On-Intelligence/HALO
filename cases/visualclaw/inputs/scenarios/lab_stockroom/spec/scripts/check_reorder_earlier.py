"""q8: docs/reorder_earlier_items.json carries the counts established in earlier rounds into the order."""
from _rows import main

main("docs/reorder_earlier_items.json", "item", [
    {"item": "Nitrile gloves size M", "on_hand": 3, "par": 4, "reorder": True},
    {"item": "10 uL filter tips", "on_hand": 1, "par": 3, "reorder": True},
    {"item": "1.5 mL microcentrifuge tubes", "on_hand": 2, "par": 2, "reorder": False},
    {"item": "70% ethanol", "on_hand": 2, "par": 3, "reorder": True},
])
