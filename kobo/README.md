# Kobo: Devotional plugin

KOReader plugin (`devotional.koplugin`) for the daily Old Paths devo EPUBs. Target: KOReader v2026.03 on Kobo, with the Zen UI plugin.

## What it does
- Full-screen list of EPUBs in `/mnt/onboard/Devo`, newest first (sorted by file name).
- Each row: date ("Mon Nov 16"), plan day, status (Unread / In progress NN% / Read), read from KOReader's own book status (sidecar).
- "Sync now" at the top runs KOReader's cloud storage sync for the server named "Old Paths Devo" (Dropbox, set up in Cloud storage). Turns Wi-Fi on if needed.
- Tap opens the book. Long-press: mark read/unread, or delete.
- Dispatcher action `devotional_show` ("Devotional"), also under Tools > Devotional.

## Zen UI integration
Devotional opens as a Zen standalone view (like History/Collections): Zen's status-row header with back chevron, Zen's bottom navbar with the Devotional tab active, other tabs close it and switch. No Zen files are edited. At runtime `main.lua`:
- builds the Menu with Zen's `standalone_page.create_menu` (flags make Zen treat it as a standalone view),
- wraps `getStandaloneTabId` on the `_G.__ZEN_UI_RAKUYOMI` extension table so Zen injects the navbar with our custom tab (`ct_1`) highlighted,
- uses Zen's shared `createStatusRow` for the header.
Everything is pcall'd. If Zen is missing, the navbar is off, the tab is not configured, or Zen changed its internals, it falls back to a plain KOReader Menu.

## Install / update
Copy the folder to the device, replacing any old copy, then restart KOReader:

    cp -R kobo/devotional.koplugin /Volumes/KOBOeReader/.adds/koreader/plugins/
    rm -f /Volumes/KOBOeReader/.adds/koreader/plugins/devotional.koplugin/._*   # macOS junk files

## Navbar tab (Zen UI)
`settings/Zen UI/config.lua` was edited with KOReader closed, under `navbar`:
- `custom_tabs` gets one entry: id `ct_1`, type `action`, label "Devotional", icon `book_open`, action `{ devotional_show = true }`
- `next_custom_id = 1`
- `show_tabs.ct_1 = true`, `show_tabs.favorites = false`
- `tab_order[6]`: `"favorites"` replaced by `"ct_1"` (same position)

Backup: `settings/Zen UI/config.lua.bak-devotional-<timestamp>`.

## Revert
Close KOReader (or eject cleanly), then copy the backup over `settings/Zen UI/config.lua`. To remove the plugin, delete `plugins/devotional.koplugin`.

Manual alternative: Zen UI settings > navbar > custom tabs > add, pick action "Devotional".

## Notes
- Sync is KOReader's stock Dropbox sync: it downloads files missing locally or with a different size. A deleted devo comes back on the next sync while it is still in Dropbox.
- Server name and folder are constants at the top of `main.lua`.
