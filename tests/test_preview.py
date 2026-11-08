"""L’aperçu conserve les contrastes et ne dépend pas de chemins d’images locaux."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import preview_weekly


class TestPreview(unittest.TestCase):
    def test_image_integree_et_texte_echappe(self):
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [
            {"text": {"content": "<script>test</script>", "link": {"url": "javascript:alert(1)"}}},
        ]}}]
        result = preview_weekly.build_preview(blocks, b"image-test", "")
        self.assertIn("data:image/png;base64,aW1hZ2UtdGVzdA==", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("javascript:", result)
        self.assertNotIn("file://", result)

    def test_encadres_distincts(self):
        for label, color in (("12 sources citées", "sources"), ("5 rencontres à l’agenda", "agenda")):
            with self.subTest(label=label):
                result = preview_weekly.render({"type": "quote", "quote": {
                    "rich_text": [{"text": {"content": label}}],
                }})
                self.assertIn(f'class="{color}"', result)

    def test_contrastes_texte_superieurs_a_sept(self):
        def luminance(value):
            rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            return sum((v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) * w
                       for v, w in zip(rgb, (0.2126, 0.7152, 0.0722)))
        for fg, bg in (("#edf5ef", "#123328"), ("#bdd2c4", "#123328"),
                       ("#a9d9ef", "#123328"), ("#f3dfac", "#443921"),
                       ("#e5f2fa", "#173b46")):
            with self.subTest(fg=fg, bg=bg):
                low, high = sorted((luminance(fg), luminance(bg)))
                self.assertGreaterEqual((high + 0.05) / (low + 0.05), 7)
