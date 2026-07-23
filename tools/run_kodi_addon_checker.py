#!/usr/bin/env python3
"""Run kodi-addon-checker with a narrow workaround for an upstream 0.0.36 bug."""

from __future__ import annotations

import sys
from typing import Any, Callable, Type


ContainsMethod = Callable[[Any, str], bool]


def guard_missing_repository_addons(repository_class: Type[Any]) -> None:
    """Treat an unavailable upstream repository as empty instead of crashing.

    kodi-addon-checker 0.0.36 can construct a Repository without its ``addons``
    attribute when external Kodi repository data cannot be loaded. Its
    ``__contains__`` method then raises AttributeError before the local add-on
    checks finish. Only that missing-attribute case is handled here; all normal
    checker errors and exit codes remain unchanged.
    """

    original_contains: ContainsMethod = repository_class.__contains__

    def safe_contains(repository: Any, addon_name: str) -> bool:
        if not hasattr(repository, "addons"):
            print(
                "WARNING: kodi-addon-checker could not load one external Kodi "
                "repository; treating it as empty for the existing-add-on check.",
                file=sys.stderr,
            )
            return False
        return original_contains(repository, addon_name)

    repository_class.__contains__ = safe_contains


def main() -> int:
    from kodi_addon_checker.addons.Repository import Repository
    from kodi_addon_checker.__main__ import main as checker_main

    guard_missing_repository_addons(Repository)
    return int(checker_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
