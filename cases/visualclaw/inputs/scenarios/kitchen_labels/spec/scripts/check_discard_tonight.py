"""q6: the speed-rack and floor discard list holds exactly masa and horchata base."""
from _rows import main

main('docs/discard_tonight.json', 'container', [
    {
        "container": "Masa"
    },
    {
        "container": "Horchata"
    }
], exact_rows=True)
