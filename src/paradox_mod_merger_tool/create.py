from __future__ import annotations

from .generate import run_generate


def run_create(*args, **kwargs):
    return run_generate(*args, **kwargs)


__all__ = ["run_create"]
