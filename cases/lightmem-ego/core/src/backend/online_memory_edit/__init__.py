from typing import Any

__all__ = ["MemoryEditError", "MemoryEditResult", "MemoryEditService"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .service import MemoryEditError, MemoryEditResult, MemoryEditService

        return {
            "MemoryEditError": MemoryEditError,
            "MemoryEditResult": MemoryEditResult,
            "MemoryEditService": MemoryEditService,
        }[name]
    raise AttributeError(name)
