from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "lib"))

from mypicsdb3.album_view import save_current_album_view
from mypicsdb3.kodi import KodiContext


if __name__ == "__main__":
    context = KodiContext()
    save_current_album_view(context, context.localize)
