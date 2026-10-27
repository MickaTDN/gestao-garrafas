"""Non-PNG payloads cannot enter unrelated image decoders before validation."""

import base64
import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from PIL import GifImagePlugin, Image, PngImagePlugin, TiffImagePlugin

from inventory.documents import validate_signature
from tests.document_fixtures import signature_png


class SignatureDecoderSecurityTests(SimpleTestCase):
    def test_disguised_formats_are_rejected_without_invoking_their_decoders(self):
        for format_name, decoder in (
            ("TIFF", TiffImagePlugin.TiffImageFile),
            ("GIF", GifImagePlugin.GifImageFile),
        ):
            with self.subTest(format=format_name):
                raw = io.BytesIO()
                Image.new("RGB", (600, 200), "white").save(raw, format=format_name)
                disguised = "data:image/png;base64," + base64.b64encode(raw.getvalue()).decode()
                with (
                    patch.object(decoder, "_open", side_effect=AssertionError("decoder reached"))
                    as open_decoder,
                    self.assertRaises(ValidationError),
                ):
                    validate_signature(disguised)
                open_decoder.assert_not_called()

    def test_valid_signature_keeps_ink_and_strips_unnecessary_metadata(self):
        raw = base64.b64decode(signature_png().split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as image:
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("Comment", "Synthetic metadata must not be retained")
            source = io.BytesIO()
            image.save(source, format="PNG", pnginfo=metadata)
        canonical = validate_signature(
            "data:image/png;base64," + base64.b64encode(source.getvalue()).decode()
        )
        with Image.open(io.BytesIO(canonical)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (600, 200))
            self.assertNotIn("Comment", image.info)
            self.assertLess(image.convert("L").getextrema()[0], 220)
