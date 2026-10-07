"""q8: the summary carries the earlier middle-shelf and bottom-shelf findings."""
from _rows import main

main('docs/closing_summary.json', 'area', [
    {
        "area": "middle shelf front row",
        "labelled_ok": 2,
        "discard": [
            "lime juice",
            "guac"
        ]
    },
    {
        "area": "bottom shelf",
        "labelled_ok": 1,
        "discard": [
            "shrimp"
        ]
    }
])
