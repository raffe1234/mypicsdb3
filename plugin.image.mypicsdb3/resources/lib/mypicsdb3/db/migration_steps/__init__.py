"""Versioned database migration steps.

A future schema change should live in a module named ``vNNNN_description.py``
and export a ``MIGRATION`` object. The central registry is intentionally kept
explicit so packaging and review cannot silently omit a migration.
"""

from .v0001_baseline import BASELINE_CHECKSUM, BASELINE_NAME

__all__ = ["BASELINE_CHECKSUM", "BASELINE_NAME"]
