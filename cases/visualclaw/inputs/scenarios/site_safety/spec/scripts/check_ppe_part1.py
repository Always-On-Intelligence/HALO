"""q3: the morning correction list holds exactly #12, #14, #15 and #17."""
from _rows import main

main('docs/ppe_part1.json', 'vest', [
    {
        "vest": "#12"
    },
    {
        "vest": "#14"
    },
    {
        "vest": "#15"
    },
    {
        "vest": "#17"
    }
], exact_rows=True)
