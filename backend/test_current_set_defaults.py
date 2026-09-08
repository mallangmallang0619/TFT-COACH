import unittest
import importlib
import game_data
import simulate_screenshot as sim

class CurrentSetDefaultsTests(unittest.TestCase):
    def test_offline_meta_contains_only_current_units_and_traits(self):
        importlib.reload(game_data)
        for comp in game_data.META_COMPS:
            self.assertIn(comp['carry'], game_data.CHAMPIONS)
            self.assertTrue(set(comp['match_traits']) <= game_data.TRAITS.keys())
        self.assertFalse(game_data.STATIC_ITEM_NAMES_BY_API)

    def test_demo_augments_belong_to_current_cache(self):
        import json
        import demo_server
        cache = json.loads(sim.CACHE_PATH.read_text(encoding="utf-8"))
        names = {entry["name"] for entry in cache["augments"]["entries"]}
        self.assertTrue(all(name in names for name, _, _ in demo_server.AUGMENTS))

    def test_simulation_defaults_resolve_current_boards(self):
        slugs = sim.default_comp_slugs()
        self.assertTrue(slugs)
        for slug in slugs:
            self.assertTrue(slug.startswith('set-18-'))
            units, label = sim.units_from_comp(slug)
            self.assertTrue(units)
            self.assertTrue(all(u['name'] in game_data.CHAMPIONS for u in units))

if __name__ == '__main__':
    unittest.main()
