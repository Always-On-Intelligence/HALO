"""q3: the dock A van list holds exactly the bikes failing a check."""
from _rows import main

main('docs/van_dock_a.json', 'bike', [
    {
        "bike": "#102"
    },
    {
        "bike": "#103"
    },
    {
        "bike": "#104"
    }
], exact_rows=True)
