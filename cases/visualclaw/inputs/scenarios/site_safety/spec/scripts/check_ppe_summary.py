"""q8: the summary carries the earlier gate, scaffold and crusher findings."""
from _rows import main

main('docs/ppe_summary_morning.json', 'area', [
    {
        "area": "gate",
        "compliant": 1,
        "non_compliant": [
            "#12"
        ]
    },
    {
        "area": "scaffold base",
        "compliant": 1,
        "non_compliant": [
            "#14",
            "#15"
        ]
    },
    {
        "area": "crusher zone",
        "compliant": 1,
        "non_compliant": [
            "#17"
        ]
    }
])
