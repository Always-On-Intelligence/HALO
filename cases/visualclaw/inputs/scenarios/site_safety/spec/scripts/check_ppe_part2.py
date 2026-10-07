"""q6: the second correction list holds exactly #24 and #27."""
from _rows import main

main('docs/ppe_part2.json', 'vest', [
    {
        "vest": "#24"
    },
    {
        "vest": "#27"
    }
], exact_rows=True)
