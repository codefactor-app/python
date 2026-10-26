import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLI(unittest.TestCase):
    def test_snapshot_option_context(self):
        from codefactor._core import argument_context
        self.assertEqual(argument_context(["scan", "--baseline", "accepted.yaml", "--baseline-mode", "regressions", "project"])["root"], "project")
        self.assertEqual(argument_context(["baseline", "create", "--capture", "all", "--root", "project"])["root"], "project")

    @unittest.skipIf(os.name == "nt", "POSIX fixture executable")
    def test_transparent_command(self):
        with tempfile.TemporaryDirectory(prefix="codefactor cli ; ") as directory:
            root = Path(directory)
            fake = root / "fake engine"
            fake.write_text(f"#!{sys.executable}\nimport json, os, sys\nprint(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'input':sys.stdin.read()}}))\nsys.stderr.write('raw diagnostic\\n')\nsys.exit(7)\n")
            fake.chmod(0o755)
            args = ["scan", "--future-option", "path ; $(literal)", "--", 'quoted "value"']
            result = subprocess.run([sys.executable, "-m", "codefactor", *args], cwd=root, env={**os.environ, "CODEFACTOR_BINARY": str(fake)}, input="stdin data\n", capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(json.loads(result.stdout), {"args": args, "cwd": str(root.resolve()), "input": "stdin data\n"})
            self.assertEqual(result.stderr, "raw diagnostic\n")

    def test_missing_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-m", "codefactor", "--version"], env={**os.environ, "CODEFACTOR_BINARY": str(Path(directory) / "missing")}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 127)
            self.assertEqual(result.stdout, "")
            self.assertIn("Cannot start Codefactor binary", result.stderr)
