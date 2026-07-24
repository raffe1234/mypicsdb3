from __future__ import annotations

from .db import Catalog, DatabaseEngine
from .filesystem import KodiFilesystem
from .kodi import KodiContext


class Runtime:
    def __init__(self):
        self.kodi = KodiContext()
        self.engine = DatabaseEngine(self.kodi.settings, self.kodi.log)
        self.catalog = Catalog(
            self.engine,
            self.kodi.log,
            rating_policy=self.kodi.settings.minimum_rating_policy,
        )
        self.catalog.initialize()
        temp_dir = self.kodi.profile_path.rstrip("/\\") + "/temp"
        self.filesystem = KodiFilesystem(temp_dir)
