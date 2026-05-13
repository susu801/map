import base64
import unittest

from visited_china_map import (
    get_supported_city_codes,
    normalize_city_codes,
    render_visited_china_map,
)


class RendererTest(unittest.TestCase):
    def test_normalizes_valid_city_codes_aliases_districts_and_duplicates(self):
        warnings = []
        result = normalize_city_codes(
            ["110100", "110101", "440106", "440100", "abc"],
            on_warning=warnings.append,
        )

        self.assertEqual(result, ["110000", "440100"])
        self.assertEqual(warnings[0].code, "abc")
        self.assertEqual(warnings[0].reason, "invalid-code")

    def test_unknown_city_codes_warn_without_throwing(self):
        warnings = []
        result = normalize_city_codes(["999999"], on_warning=warnings.append)

        self.assertEqual(result, [])
        self.assertEqual(warnings[0].code, "999999")
        self.assertEqual(warnings[0].reason, "unknown-city")

    def test_renders_png_data_url(self):
        image = render_visited_china_map(
            ["110000", "310101", "440305"],
            width=320,
            height=240,
        )

        self.assertTrue(image.startswith("data:image/png;base64,"))
        png = base64.b64decode(image.removeprefix("data:image/png;base64,"))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_exposes_supported_city_codes(self):
        supported = get_supported_city_codes()

        self.assertIn("110000", supported)
        self.assertIn("440100", supported)
        self.assertIn("710000", supported)

if __name__ == "__main__":
    unittest.main()
