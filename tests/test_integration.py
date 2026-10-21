import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codefactor import Codefactor, CodefactorError
from codefactor import _installer


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codefactor python ; ")
        self.root = Path(self.temp.name)
        sources = {
            "calls.php": "<?php function leaf(){return 1;} function caller(){return leaf();}",
            "calls.py": "def leaf():\n    return 1\ndef caller(a, b, c):\n    return leaf()\n",
            "calls.ts": "export function leaf(){return 1;} export function caller(){return leaf();}",
            "calls.js": "function leaf(){return 1;} function caller(){return leaf();}",
            "calls.rs": "fn leaf()->i32{1} fn caller()->i32{leaf()}",
        }
        for name, source in sources.items():
            (self.root / name).write_text(source)
        self.client = Codefactor()

    def tearDown(self):
        self.temp.cleanup()

    def test_all_languages_and_queries(self):
        report = self.client.scan(self.root, architecture=False).data
        self.assertEqual(report["summary"]["files"], 5)
        self.assertEqual(report["summary"]["functions"], 10)
        self.assertEqual(report["parse_errors"], [])
        self.assertEqual(self.client.scan(self.root, languages=["python"]).data["summary"]["files"], 1)
        self.assertIn("root", self.client.ast(self.root / "calls.py").data)
        self.assertTrue(self.client.graph("calls.caller", self.root, "callees", 2).data["edges"])

    def test_violations_and_config_errors(self):
        config = self.root / "limits.yaml"
        config.write_text("limits:\n  function_params: {warn: 1, error: 2}\ncache:\n  enabled: false\n")
        result = self.client.scan(self.root, config=config)
        self.assertEqual(result.exit_code, 2)
        self.assertGreater(result.data["summary"]["errors"], 0)
        config.write_text("[invalid: yaml")
        with self.assertRaises(CodefactorError) as raised:
            self.client.scan(self.root, config=config)
        self.assertEqual(raised.exception.exit_code, 3)
        with self.assertRaises(CodefactorError):
            self.client.scan(self.root / "missing")

    @unittest.skipIf(os.name == "nt", "POSIX fixture executable")
    def test_timeout(self):
        fake = self.root / "slow"
        fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
        fake.chmod(0o755)
        with self.assertRaisesRegex(CodefactorError, "timed out"):
            Codefactor(fake, timeout=0.05).scan(self.root)

    def test_download_rejects_corrupted_binary(self):
        import json
        config = json.loads((_installer.ROOT / "release.json").read_text())
        (self.root / "release.json").write_text(json.dumps(config))
        platform = _installer.platform_id()
        manifest = {"version": "0.1.0", "platform": platform, "file": f"codefactor-{platform}", "size": 4, "sha256": "0" * 64}
        with patch.object(_installer, "ROOT", self.root), patch.object(_installer, "download", side_effect=[json.dumps(manifest).encode(), b"oops"]), patch.dict(os.environ):
            os.environ.pop("CODEFACTOR_BINARY", None)
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                _installer.install()
            self.assertFalse((_installer.binary_path()).exists())


if __name__ == "__main__":
    unittest.main()
