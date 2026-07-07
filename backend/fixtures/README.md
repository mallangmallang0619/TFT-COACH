# Detection fixtures

Labeled frames the accuracy harness (`backend/eval_detection.py`) scores the
detector against. Each fixture is a pair:

```
<name>.png      a frame (real screenshot, or a synthesized board)
<name>.json     ground truth for that frame
```

### JSON schema

```json
{
  "source": "real | synthetic",
  "comp": "set-17-... (optional, for synthetic)",
  "realism": "none | light | heavy (optional, for synthetic)",
  "board": [
    { "name": "Meepsie", "row": 1, "col": 6 },
    { "name": "Pyke",    "row": 3, "col": 2 }
  ]
}
```

`name` must match a champion template stem in `assets/templates/champions/`.
`row`/`col` are board hex coordinates (4 rows × 7 cols; `boardIndex = row*7 + col`).
Only list champions that have a template — summons/specials the detector can't
match (e.g. Galio) should be omitted.

### Adding real fixtures (the valuable ones)

1. Capture a TFT screenshot at the configured `GAME_RESOLUTION`.
2. Save it here as `my_game_4-2.png`.
3. Hand-write `my_game_4-2.json` listing the champions on the board.
4. Run `python backend/eval_detection.py --fixtures`.

The synthetic `*__light.png` / `*__heavy.png` files here were generated with
`--save-fixtures` as examples; real screenshots are what actually validate the
detector. Regenerate or delete the synthetic ones freely.
