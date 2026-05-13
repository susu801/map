import unittest

from visited_china_map.server import APP_HTML, data_url_to_png_bytes, render_payload


class ServerPayloadTest(unittest.TestCase):
    def test_render_payload_returns_image_and_metadata(self):
        response = render_payload(
            {
                "cityCodes": ["110100", "440305", "bad", "999999"],
                "width": 180,
                "height": 140,
            }
        )

        self.assertTrue(response["image"].startswith("data:image/png;base64,"))
        self.assertEqual(response["normalizedCityCodes"], ["110000", "440300"])
        self.assertEqual(response["width"], 180)
        self.assertEqual(response["height"], 140)
        self.assertEqual(
            response["warnings"],
            [
                {"code": "bad", "reason": "invalid-code"},
                {"code": "999999", "reason": "unknown-city"},
            ],
        )

    def test_rejects_missing_city_codes(self):
        with self.assertRaisesRegex(ValueError, "cityCodes"):
            render_payload({})

    def test_rejects_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "width"):
            render_payload({"cityCodes": [], "width": 0})

    def test_accepts_theme(self):
        response = render_payload(
            {
                "cityCodes": ["110000"],
                "width": 120,
                "height": 90,
                "theme": {"visited_fill": "#ff3366"},
            }
        )

        self.assertTrue(response["image"].startswith("data:image/png;base64,"))

    def test_converts_data_url_to_png_bytes(self):
        response = render_payload({"cityCodes": ["110000"], "width": 120, "height": 90})
        png = data_url_to_png_bytes(response["image"])

        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_app_html_contains_render_form(self):
        self.assertIn("中国城市打卡地图测试器", APP_HTML)
        self.assertIn('fetch("/render"', APP_HTML)
        self.assertIn('id="codes"', APP_HTML)


if __name__ == "__main__":
    unittest.main()
