import json
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def test_saved_reviews_validate():
    schema = json.loads((ROOT / 'halo' / 'read' / 'schema.json').read_text())
    for f in (ROOT / 'results' / 'read' / 'reviews').glob('*/*.json'):
        review = json.loads(f.read_text()); review.pop('_meta', None)
        jsonschema.validate(review, schema)
