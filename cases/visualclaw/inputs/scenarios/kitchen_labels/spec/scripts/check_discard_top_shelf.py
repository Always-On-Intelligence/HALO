"""q3: the top-shelf discard list holds exactly the containers without both dates."""
from _rows import main

main('docs/discard_top_shelf.json', 'container', [
    {
        "container": "Pico de gallo"
    },
    {
        "container": "Crema"
    },
    {
        "container": "Rice"
    }
], exact_rows=True)
