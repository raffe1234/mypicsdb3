"""Versioned database migration steps.

Each schema change lives in a module named ``vNNNN_description.py`` and exports
a ``MIGRATION`` object. The central registry in ``db/migrations.py`` remains
explicit so packaging and review cannot silently omit a migration.
"""

from .v0001_baseline import BASELINE_CHECKSUM, BASELINE_NAME

__all__ = ["BASELINE_CHECKSUM", "BASELINE_NAME"]
