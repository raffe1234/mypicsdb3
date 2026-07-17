# Estuary integration for Kodi 21 Omega

Standard Estuary contains only the `sources://pictures/` category widget. Kodi
add-ons must not modify another add-on's files, and standard Estuary updates can
overwrite local edits. Create a separately named Estuary fork.

## Prepare a skin fork

From a clone of the Kodi Omega branch, run:

```bash
python3 /path/to/mypicsdb3/contrib/estuary/apply_patch.py \
  /path/to/xbmc/addons/skin.estuary
```

The helper:

1. changes the add-on id to `skin.estuary.mypicsdb3`;
2. changes the display name to `Estuary MyPicsDB 3`;
3. replaces only the Pictures home group with the supplied Omega block;
4. writes `.mypicsdb3-backup` copies before changing files.

Package the resulting `skin.estuary.mypicsdb3` directory as a Kodi add-on zip.
The skin widgets are visible only when `plugin.image.mypicsdb3` is installed.

## Added rows

- Media sources
- Recently taken
- Recently added
- Random memories
- Recent albums
- Random albums
- On this day

The widget IDs are in the 4100–4700 range and the scrollbar is 4010.

## Important

The supplied block targets the Omega `Home.xml` structure. Recheck it when
porting to Kodi 22 or a later Estuary revision.
