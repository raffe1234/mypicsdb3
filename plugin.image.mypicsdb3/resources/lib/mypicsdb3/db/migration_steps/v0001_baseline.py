from __future__ import annotations

import hashlib


BASELINE_NAME = "initial catalogue schema"
BASELINE_CHECKSUM = hashlib.sha256(
    b"mypicsdb3:schema:1:initial-catalogue-schema"
).hexdigest()
