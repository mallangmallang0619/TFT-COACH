"""Validate the checked-in current-set snapshot against Riot data services.

Set 18's Unreal launch temporarily split useful data across services:

* Data Dragon has the real DA_* shop roster, costs, and portraits, including
  all nine Avatar Lux rows, but no trait membership.
* CommunityDragon has Set 18 trait definitions/breakpoints, but its usual set
  roster is incomplete and reports jungle units as generic PvE actors.

The runtime snapshot in ``backend/set18_data.py`` joins those pieces.  This
command makes upstream drift visible without rewriting reviewed gameplay data:

    python scripts/sync_set_data.py

It exits non-zero for cost/id/trait-breakpoint drift. Riftbeasts absent from
Data Dragon's shop file are reported separately and validated by local tests.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from set18_data import CHAMPIONS, LUX_FORMS, SET_NUMBER, TRAITS  # noqa: E402

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPIONS_URL = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/"
    "tft-champion.json"
)
CDRAGON_URL = "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"
USER_AGENT = "tft-coach-set-sync/0.1"

# These playable Set 18 monsters are not currently emitted as shop rows by
# Data Dragon after the Unreal migration.
RIFTBEAST_SOURCE_GAP = {
    "Cinderling", "Pebbles", "Gromp", "Murkwolf", "Scuttlecrab", "Krug",
    "Mama Beak", "Ancient Sentinel", "Brambleback", "Elder Dragon",
}


def _get_json(url: str) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _ddragon_set_entries(payload: dict) -> dict[str, dict]:
    marker = f"/Sets/TFTSet{SET_NUMBER}/Shop/".lower()
    result: dict[str, dict] = {}
    for path, entry in (payload.get("data") or {}).items():
        if marker not in path.lower():
            continue
        api_name = entry.get("id")
        if api_name:
            result[api_name] = entry
    return result


def validate(ddragon: dict, cdragon: dict) -> list[str]:
    errors: list[str] = []
    by_api = _ddragon_set_entries(ddragon)

    for name, data in CHAMPIONS.items():
        if name in RIFTBEAST_SOURCE_GAP:
            continue
        api_name = data.get("api_name")
        entry = by_api.get(api_name)
        if entry is None:
            errors.append(f"{name}: Riot shop id missing: {api_name}")
            continue
        if int(entry.get("cost", -1)) != int(data["cost"]):
            errors.append(
                f"{name}: cost {data['cost']} locally, {entry.get('cost')} upstream"
            )

    upstream_traits = {
        trait.get("name"): [
            int(effect["minUnits"])
            for effect in trait.get("effects") or []
            if effect.get("minUnits") is not None
        ]
        for trait in ((cdragon.get("sets") or {}).get(str(SET_NUMBER), {}) or {}).get(
            "traits", []
        )
    }
    for name, data in TRAITS.items():
        upstream = upstream_traits.get(name)
        # Eclipse is a hidden derived trait and Rival has repeated internal
        # entries; their user-facing breakpoints are intentionally normalized.
        if name in {"Eclipse", "Rival"}:
            continue
        if upstream is None:
            errors.append(f"trait missing upstream: {name}")
        elif upstream != data["breakpoints"]:
            errors.append(
                f"{name}: breakpoints {data['breakpoints']} locally, {upstream} upstream"
            )

    lux_entries = [by_api.get(api_name) for api_name in LUX_FORMS.values()]
    lux_entries = [entry for entry in lux_entries if entry]
    portrait_names = {
        (entry.get("image") or {}).get("full") for entry in lux_entries
    }
    if len(lux_entries) != len(LUX_FORMS):
        errors.append(
            f"Lux: found {len(lux_entries)}/{len(LUX_FORMS)} Avatar forms upstream"
        )
    if len(portrait_names) != 1:
        errors.append(f"Lux: expected one shared portrait, got {sorted(portrait_names)}")
    return errors


def main() -> int:
    versions = _get_json(VERSIONS_URL)
    if not isinstance(versions, list) or not versions:
        print("Data Dragon returned no versions.", file=sys.stderr)
        return 1
    version = versions[0]
    ddragon = _get_json(CHAMPIONS_URL.format(version=version))
    cdragon = _get_json(CDRAGON_URL)
    assert isinstance(ddragon, dict) and isinstance(cdragon, dict)

    errors = validate(ddragon, cdragon)
    print(f"Set {SET_NUMBER} validation against Data Dragon {version}")
    print(f"  runtime identities: {len(CHAMPIONS)} (Lux forms + generic OCR label)")
    print(f"  Lux Avatar forms:   {len(LUX_FORMS)} (pooled into one ML class)")
    print(f"  source-gap monsters:{len(RIFTBEAST_SOURCE_GAP):>3}")
    if errors:
        print("\nDrift detected:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("  result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
