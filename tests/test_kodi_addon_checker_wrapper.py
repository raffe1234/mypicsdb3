from tools.run_kodi_addon_checker import guard_missing_repository_addons


def test_missing_external_repository_is_treated_as_empty(capsys):
    class Repository:
        def __contains__(self, addon_name):
            return addon_name in self.addons

    guard_missing_repository_addons(Repository)

    unavailable = Repository()
    assert "plugin.image.mypicsdb3" not in unavailable
    assert "could not load one external Kodi repository" in capsys.readouterr().err

    available = Repository()
    available.addons = ["plugin.image.mypicsdb3"]
    assert "plugin.image.mypicsdb3" in available
