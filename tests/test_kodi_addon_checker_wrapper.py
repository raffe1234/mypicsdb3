from tools.run_kodi_addon_checker import guard_missing_repository_addons


def test_missing_external_repository_is_treated_as_empty(capsys):
    class Repository:
        def __contains__(self, addon_name):
            return addon_name in self.addons

        def rdepends(self, addon_name):
            return [
                addon for addon in self.addons if addon.get("dependency") == addon_name
            ]

    guard_missing_repository_addons(Repository)

    unavailable = Repository()
    assert "plugin.image.mypicsdb3" not in unavailable
    assert tuple(unavailable.rdepends("plugin.image.mypicsdb3")) == ()
    warning = capsys.readouterr().err
    assert warning.count("could not load one external Kodi repository") == 2

    available = Repository()
    available.addons = [
        {"id": "skin.estuary.mypicsdb3", "dependency": "plugin.image.mypicsdb3"},
        {"id": "plugin.image.mypicsdb3", "dependency": "xbmc.python"},
    ]
    assert "plugin.image.mypicsdb3" not in available
    assert available.addons[1] in available
    assert available.rdepends("plugin.image.mypicsdb3") == [available.addons[0]]
