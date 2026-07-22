# Integrating MyPicsDB 3 with Kodi skins

This guide describes how a Kodi skin can display MyPicsDB 3 picture and
album widgets. It is intended for skin authors and maintainers.

The shipped `skin.estuary.mypicsdb3` package is the reference implementation
for Kodi 21 Omega. Other skins can use the same stable plugin paths, but
layout, focus, visibility and navigation must be adapted to each skin.

## What is currently supported

MyPicsDB 3 currently builds and tests one integrated skin:

```text
skin.estuary.mypicsdb3
```

Other integrations fall into three groups:

1. **Skins with user-configurable widgets** may be able to select a
   MyPicsDB 3 view without changing skin source.
2. **Estuary-derived skins** can reuse the integration concepts and may be
   able to adapt the Estuary include calls.
3. **Non-Estuary skins** must use their own home-screen and widget
   architecture.

A skin being distributed through Kodi's official add-on repository does not
mean that it is Estuary-based or XML-compatible with Estuary.

Kodi installs Estuary as its default full-screen skin and Estouchy as its
touch-oriented alternative. Treat Estouchy as a separate integration, not
as an Estuary fragment drop-in.

## Integration contract

MyPicsDB 3 exposes read-only `plugin://` endpoints. A widget endpoint only
queries already indexed database rows and must never start a source scan.

The skin is responsible for:

- container type, dimensions and item layouts;
- unique control, list and scrollbar IDs;
- headings and localization;
- hiding disabled or empty rows cleanly;
- using the Pictures window for folder navigation;
- focus, Back, mouse, touch, keyboard and remote behaviour;
- dependency and version declarations.

## Stable widget endpoints

| View | Plugin path | Result |
|---|---|---|
| Recently taken | `plugin://plugin.image.mypicsdb3/recent-taken?limit=15` | Pictures |
| Recently added | `plugin://plugin.image.mypicsdb3/recent-added?limit=15` | Pictures |
| Random memories | `plugin://plugin.image.mypicsdb3/random?limit=15` | Pictures |
| Recent albums | `plugin://plugin.image.mypicsdb3/recent-folders?limit=15` | Folders |
| Random albums | `plugin://plugin.image.mypicsdb3/random-folders?limit=15` | Folders |
| On this day | `plugin://plugin.image.mypicsdb3/on-this-day?limit=15` | Pictures |
| Favorites | `plugin://plugin.image.mypicsdb3/favorites?limit=15` | Pictures |
| Rated pictures | `plugin://plugin.image.mypicsdb3/rated?limit=15` | Pictures |
| Geotagged pictures | `plugin://plugin.image.mypicsdb3/geotagged?limit=15` | Pictures |
| Years | `plugin://plugin.image.mypicsdb3/years` | Folders |
| Cameras | `plugin://plugin.image.mypicsdb3/cameras` | Folders |
| Keywords | `plugin://plugin.image.mypicsdb3/keywords` | Folders |

Keep home-screen limits small. Fifteen items is the project default. The Estuary MyPicsDB 3 integration supports 1–50 items per row.

Random endpoints should normally disable Kodi 21's synthetic "more" item by
using `browse="never"` or the equivalent parameter in the skin's widget
include.

## Minimal dynamic-content example

Kodi list, fixed-list, wrap-list and panel containers can obtain dynamic
content directly from a plugin:

```xml
<control type="panel" id="9100">
  <visible>System.HasAddon(plugin.image.mypicsdb3)</visible>
  <content target="pictures"
           limit="15"
           browse="never">plugin://plugin.image.mypicsdb3/recent-taken?limit=15</content>

  <!-- Use the target skin's normal dimensions, itemlayout,
       focusedlayout, navigation and animations. -->
</control>
```

This is a structural example, not a complete widget. Copy the established
widget pattern from the target skin.

Use `target="pictures"` for album and navigation endpoints so folder items
open in the Pictures window.

## Reading the MyPicsDB 3 row settings

MyPicsDB 3 exposes nine string settings:

```text
home_row_1
home_row_2
home_row_3
home_row_4
home_row_5
home_row_6
home_row_7
home_row_8
home_row_9
```

Supported values are:

| Value | View |
|---|---|
| `none` | No row |
| `recent_taken` | Recently taken |
| `recent_added` | Recently added |
| `random_memories` | Random memories |
| `recent_albums` | Recent albums |
| `random_albums` | Random albums |
| `on_this_day` | On this day |
| `favorites` | Favorites |
| `rated` | Rated pictures |
| `geotagged` | Geotagged pictures |

The Media sources visibility setting is:

```text
show_media_sources
```

Kodi 20 and later can read these values from skin XML:

```xml
<visible>
  System.HasAddon(plugin.image.mypicsdb3)
  + String.IsEqual(
      Addon.SettingStr(plugin.image.mypicsdb3,home_row_1),
      recent_taken
    )
</visible>
```

Media sources can use:

```xml
<visible>
  Addon.SettingBool(plugin.image.mypicsdb3,show_media_sources)
</visible>
```

A skin with its own widget editor can ignore these row settings and store
the selected plugin path as a skin setting instead.

## Estuary-derived skins

The reference integration uses Estuary-specific includes such as its widget
group and poster-list includes.

Start from:

```text
contrib/estuary/Home-pictures-group.xml
docs/ESTUARY_INTEGRATION.md
```

Before adapting the fragment:

1. Compare the target skin's `Home.xml` and include definitions with the
   pinned official Estuary source.
2. Verify every include name and parameter.
3. Allocate IDs that do not collide with the target skin.
4. Verify the Pictures menu item and visibility condition.
5. Test zero, one and more-than-limit results.
6. Repeat the review after each upstream skin update.

Do not assume that an Estuary-derived skin still uses control groups `4000`
and `17000`. Those boundaries belong to the pinned official Estuary source
used by the current builder.

## Non-Estuary skins

Do not copy `Home-pictures-group.xml` directly into a non-Estuary skin.
Include names such as `WidgetGroupListCommon` and `WidgetListPoster` are
Estuary implementation details, not Kodi-wide APIs.

Instead:

1. Find the skin's home window and existing widget container or include.
2. Duplicate the skin's own pattern for a comparable media widget.
3. Replace the content path with a MyPicsDB 3 endpoint.
4. Set the target to Pictures for folder endpoints.
5. Add `System.HasAddon(plugin.image.mypicsdb3)` visibility.
6. Add headings through the target skin's localization system.
7. Add row selection through either the skin's settings framework or the
   MyPicsDB 3 settings described above.
8. Test every supported input method.

Aeon-, Confluence-, Amber- and other skin families require separate
integrations even when a particular skin is distributed through Kodi's
official repository.

## Skins with a widget picker

If the skin has a user-configurable widget picker, check whether it can
browse to:

```text
Pictures > Picture add-ons > MyPicsDB 3
```

Select the desired view as the widget source. If the picker accepts a manual
path, use one of the stable plugin paths above.

This avoids maintaining a fork, but the exact workflow and layouts depend
on the skin.

## Packaging a maintained skin fork

Never modify Kodi's installed standard skin in place. A maintained fork
should:

- use a unique add-on ID and display name;
- retain upstream license, copyright and attribution;
- declare the compatible `xbmc.gui` version;
- declare `plugin.image.mypicsdb3` as a dependency when required;
- have its own version and release process;
- state clearly that it is not an official Kodi release.

Kodi's official add-on rules do not normally accept simple skin mods unless
the result is substantially different and independently maintained.

A required dependency can be declared in `addon.xml`:

```xml
<requires>
  <!-- Keep the skin's existing imports. -->
  <import addon="plugin.image.mypicsdb3" version="0.2.3"/>
</requires>
```

An optional integration can omit the hard dependency and hide its controls
with `System.HasAddon(...)`.

## Localization

Avoid relying on another add-on's numeric localization IDs unless that
behaviour has been tested on the supported Kodi versions.

Prefer:

- strings in the skin's own language catalogue;
- the target skin's normal localization mechanism;
- fixed English headings only in an explicitly English development build.

The reference Estuary fork writes its row headings directly because
cross-add-on localization was unreliable during testing.

## Empty rows

Favorites, Geotagged pictures and On this day can legitimately return no
items. Use the target skin's normal empty-widget handling so the container
does not reserve a large blank area.

Do not start a scan as a fallback for an empty widget.

## Compatibility policy

Record support by exact Kodi and skin version:

| Kodi | Skin | Skin version | MyPicsDB 3 | Status |
|---|---|---|---|---|
| 21 Omega | Estuary MyPicsDB 3 | project release | matching release | Built and tested |
| 21 Omega | Another skin | exact version | minimum tested version | Experimental or supported |

Do not describe an entire skin family as supported after testing only one
version.

## Test checklist

Test in a real Kodi installation:

- no XML or include errors in `kodi.log`;
- Pictures opens with and without MyPicsDB 3 installed;
- opening the home screen never starts a scan;
- each enabled row uses the correct endpoint and heading;
- a row set to `none` is absent;
- empty results do not break the layout;
- pictures open correctly;
- albums open in the Pictures window;
- focus and Back navigation are logical;
- keyboard, remote, mouse and touch work where supported;
- random rows do not gain an unwanted "more" item;
- switching skins is safe;
- skin and Kodi updates do not overwrite a separate fork;
- dependencies install and update correctly.

## Reference implementation limits

`skin.estuary.mypicsdb3` is generated per Kodi channel by replacing the matching
official Estuary Pictures group between known control-group boundaries. It is
intentionally strict and reproducible, not a general patcher for arbitrary
skins.

Support for another skin should be implemented as a reviewed, versioned
integration in that skin's source or as a separately maintained fork.

## Official Kodi references

- [Skinning Manual](https://kodi.wiki/view/Skinning_Manual)
- [Dynamic List Content](https://kodi.wiki/view/Dynamic_List_Content)
- [InfoLabels](https://kodi.wiki/view/InfoLabels)
- [List of boolean conditions](https://kodi.wiki/view/List_of_boolean_conditions)
- [Addon.xml](https://kodi.wiki/view/Addon.xml)
- [Add-on rules](https://kodi.wiki/view/Add-on_rules)
- [Changing skins](https://kodi.wiki/view/HOW-TO:Change_skins)
