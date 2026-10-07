"""q6: the dock D van list holds exactly #402, #405 and #406."""
from _rows import main

main('docs/van_dock_d.json', 'bike', [
    {
        "bike": "#402"
    },
    {
        "bike": "#405"
    },
    {
        "bike": "#406"
    }
], exact_rows=True)
