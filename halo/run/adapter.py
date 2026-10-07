"""Base class for a case adapter. Each case folder has adapter.py defining `Adapter(BaseAdapter)`.

An adapter connects HALO to one system. It declares where each coupling channel (and, for
learning systems, each evidence step) passes through the system's code, and runs one input
item with a set of those sites cut. Everything else in the run comes from the system's own code.
"""

class BaseAdapter:
    channels = {}   # e.g. {'M->S': 'user profile inserted into the perception prompt'}
    steps = {}      # e.g. {'revision': 'reflection writes the revised prompt to the store'}

    def __init__(self, case_dir, llm):
        self.case_dir, self.llm = case_dir, llm   # llm(system, user, tag='') -> str, the system's backbone

    def items(self):
        """Return the list of input items (dicts with an 'id')."""
        raise NotImplementedError

    def run(self, item, cut, sample):
        """Run one item with the sites in `cut` (a list of channel or step names) cut.
        Return a JSON-serializable dict. Put judgeable text under 'output' and numeric
        measurements under 'metrics'."""
        raise NotImplementedError
