from __future__ import annotations

from .build import run_build


def run_assemble(*args, **kwargs):
    return run_build(*args, **kwargs)


__all__ = ["run_assemble"]
