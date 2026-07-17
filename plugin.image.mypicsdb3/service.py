from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "lib"))
from mypicsdb3.entrypoints import service_main

if __name__ == "__main__":
    service_main()
