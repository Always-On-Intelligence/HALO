"""Shared helpers for fake modules: unknown attributes become logged placeholders."""
from omi_harness.loader import Placeholder, STUB_CALLS


def missing(module_name: str):
    def __getattr__(name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        STUB_CALLS[f'(fake-missing) {module_name}.{name}'] += 1
        return Placeholder(f'{module_name}.{name}')
    return __getattr__
