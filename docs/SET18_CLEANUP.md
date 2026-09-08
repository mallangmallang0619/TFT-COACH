# Set 18 cleanup — September 8, 2026

Removed obsolete Set 17 roster/trait/comp/augment seed tables and PsyOps item
aliases. Offline comp seeds now come directly from `set18_data.py`; curated
ratings are populated by the current-set cache and live sync. Simulation and
evaluation defaults select current-set boards with usable details from the cache.
Demo roles use current traits, and demo augment examples match the Set 18 cache.

Removed 45 generated retired champion portraits, 33 retired trait icons, 17
retired emblem icons (including their generated frontend copies), six historical
fixture files, and 115 historical debug files. Removed the standalone HUD check
that depended exclusively on the retired screenshot; current-set OCR tests and
old-set rejection/compatibility tests remain.

Preserved because identification is uncertain or the data remains relevant:

- Shared champion portraits, component artwork, and generic item artwork:
  filenames do not establish when the artwork originated, and current units/items
  still use them.
- Shared-name artwork under `backend/_debug/champ_cdragon` and
  `backend/_debug/traits_cdragon`.
- Other local captures in `backend/_debug`: the folder mixes dated diagnostics
  from different sets; no blanket date-based deletion was performed.
- `backend/_training`, `backend/_training_rejected`, and user-data training:
  no training data was deleted.
- Existing modified `assets/tactics_cache.json`, `assets/tftacademy_cache.json`,
  and local logs remain outside the intended commit.

The Windows installer was rebuilt locally. The user's existing D: installation
was not modified. The installer has not been published as a release.
