"""The published error document may return 404, but must match its release hash."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


spec = importlib.util.spec_from_file_location(
    "verify_deployed", Path(__file__).resolve().parents[1] / "scripts/verify_deployed.py"
)
deployed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployed)


class VerifyErrorDocumentTests(unittest.TestCase):
    def verify(self, *, error_body=b"missing", missing_pdf=False):
        base = "https://example.org/"
        assets = {"404.html": b"missing", "book.pdf": b"pdf"}
        build = {"build": "test", "version": "0.3", "files": len(assets)}
        manifest = {**build, "files": list(assets), "hashes": {
            path: hashlib.sha256(body).hexdigest() for path, body in assets.items()
        }}
        responses = {**assets, "build.json": json.dumps(build).encode(),
                     "precache.json": json.dumps(manifest).encode(),
                     "": "<title>Правила — Бронепехота</title>".encode(), "sw.js": b"test"}

        def urlopen(request, timeout):
            path = request.full_url.removeprefix(base)
            if path == "404.html" or (missing_pdf and path == "book.pdf"):
                body = error_body if path == "404.html" else assets[path]
                raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(body))
            return io.BytesIO(responses[path])

        with patch.object(deployed, "urlopen", side_effect=urlopen):
            deployed.verify(base, "test")

    def test_verified_404_document_is_accepted(self):
        self.verify()

    def test_wrong_404_document_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Published asset differs: 404.html"):
            self.verify(error_body=b"hosting error page")

    def test_another_asset_with_404_is_rejected_even_with_matching_bytes(self):
        with self.assertRaisesRegex(ValueError, "Published asset unavailable: book.pdf"):
            self.verify(missing_pdf=True)


if __name__ == "__main__":
    unittest.main()
