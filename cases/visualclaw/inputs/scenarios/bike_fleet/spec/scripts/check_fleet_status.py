"""q8: the fleet status carries the earlier dock A and dock B findings."""
from _rows import main

main('docs/fleet_status.json', 'dock', [
    {
        "dock": "Dock A",
        "ride_ready": 2,
        "van": [
            "#102",
            "#103",
            "#104"
        ]
    },
    {
        "dock": "Dock B",
        "ride_ready": 3,
        "van": [
            "#203",
            "#204",
            "#205"
        ]
    }
])
