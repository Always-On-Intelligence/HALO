from halo.read.vote import vote_cell


def test_majority_and_splits():
    assert vote_cell({'a': 'reported', 'b': 'reported', 'c': 'absent'}, 'channel') == ('reported', '2 of 3')
    assert vote_cell({'a': 'reported', 'b': 'absent', 'c': 'insufficient'}, 'channel') == ('insufficient', 'no majority')
    assert vote_cell({'a': 'stated', 'b': 'not_stated'}, 'step') == ('not_stated', 'no majority')
    assert vote_cell({'a': 'stated'}, 'step') == ('stated', 'single review')
    assert vote_cell({}, 'step') == (None, 'missing')
