from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MigrationAction = Callable[[object, object], None]


@dataclass(frozen=True)
class MigrationStep:
    version: int
    name: str
    checksum: str
    apply: MigrationAction
