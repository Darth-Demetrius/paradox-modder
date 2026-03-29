from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RecordType = Literal["object", "preamble", "file"]
PREAMBLE_NAME = "__preamble__"
WHOLE_FILE_NAME = "__whole_file__"


@dataclass(frozen=True)
class ConflictKey:
    source_path: str
    name: str
    record_type: RecordType

    @property
    def tracking_id(self) -> str:
        return f"{self.record_type}:{self.source_path}:{self.name}"


@dataclass(frozen=True)
class SnapshotRecord:
    metadata: dict[str, str]
    body: str
    position: int
    source_hash: str


@dataclass(frozen=True)
class ConflictSource:
    ref: str
    position: int
    source_hash: str
    supported_version: str
    body: str


@dataclass(frozen=True)
class ConflictEntry:
    key: ConflictKey
    output_rel: str
    merged_path: Path
    status: str
    sources: tuple[ConflictSource, ...]
