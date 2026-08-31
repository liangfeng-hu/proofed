from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from unittest import mock

from proofed import __version__, cli
from proofed.kernel import Kernel, KernelError
from proofed.receipt import verify_bundle
from proofed.subject import current_subject


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "examples" / "false-completion"
VECTORS = REPO_ROOT / "spec" / "test-vectors" / "vectors.json"


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def call_cli(argv: list[str], stdin: dict | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    input_stream = io.StringIO(json.dumps(stdin)) if stdin is not None else sys.stdin
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.stdin", input_stream):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class ProofedEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy2(DEMO_ROOT / "calculator.py", self.root / "calculator.py")
        shutil.copytree(DEMO_ROOT / "tests", self.root / "tests")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.name=demo", "-c", "user.email=demo@example.invalid", "commit", "-qm", "baseline"],
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def start_rejected_run(self) -> Path:
        with working_directory(self.root):
            self.assertEqual(call_cli(["init"])[0], 0)
            self.assertEqual(call_cli(["run", ".", "--intent", "verify integer addition"])[0], 0)
            code, _out, err = call_cli(["verify"])
            self.assertEqual(code, 2)
            self.assertIn("missing tests_passed", err)
        return next((self.root / ".proofed" / "receipts").glob("completion-*.json"))

    def test_false_completion_red_green_and_stale_subject(self) -> None:
        self.start_rejected_run()
        with working_directory(self.root):
            code, out, err = call_cli(["verify", "--run-tests"])
            self.assertEqual((code, err), (0, ""))
            self.assertIn("PASSED", out)
            receipt = next((self.root / ".proofed" / "receipts").glob("completion-*.json"))
            bundle = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(verify_bundle(bundle, expected_subject=current_subject(self.root)["digest"]["sha256"]), [])
            self.assertEqual(call_cli(["check-receipt", str(receipt), "--current", "."])[0], 0)

            self.root.joinpath("calculator.py").write_text("def add(left: int, right: int) -> int:\n    return left - right\n", encoding="utf-8")
            code, _out, err = call_cli(["check-receipt", str(receipt), "--current", "."])
            self.assertEqual(code, 4)
            self.assertIn("STALE_SUBJECT", err)

    def test_python_and_javascript_verifiers_match_current_subject(self) -> None:
        self.start_rejected_run()
        with working_directory(self.root):
            self.assertEqual(call_cli(["verify", "--run-tests"])[0], 0)
        receipt = next((self.root / ".proofed" / "receipts").glob("completion-*.json"))
        python = subprocess.run(
            [sys.executable, str(REPO_ROOT / "verifiers/python/check_receipt.py"), str(receipt), "--current", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )
        node = subprocess.run(
            ["node", str(REPO_ROOT / "verifiers/javascript/check-receipt.mjs"), str(receipt), "--current", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual((python.returncode, node.returncode), (0, 0), (python.stderr, node.stderr))

    def test_claude_stop_hook_blocks_twice_then_holds(self) -> None:
        self.start_rejected_run()
        payload = {
            "cwd": str(self.root),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "background_tasks": [],
            "session_crons": [],
        }
        with working_directory(self.root):
            first = call_cli(["hook-stop"], payload)
            second = call_cli(["hook-stop"], payload)
            third = call_cli(["hook-stop"], payload)
        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        self.assertIn('"decision": "block"', first[1])
        self.assertIn('"decision": "block"', second[1])
        self.assertEqual(third[1], "")
        state = Kernel(self.root).active_run()
        self.assertEqual(state["phase"], "HOLD")
        self.assertEqual(state["reason"]["code"], "BLOCK_BUDGET_EXHAUSTED")

    def test_claude_stop_hook_reentry_is_allowed_and_recorded(self) -> None:
        self.start_rejected_run()
        payload = {
            "cwd": str(self.root),
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "background_tasks": [],
            "session_crons": [],
        }
        with working_directory(self.root):
            code, out, err = call_cli(["hook-stop"], payload)
        self.assertEqual((code, out, err), (0, "", ""))
        state = Kernel(self.root).active_run()
        self.assertEqual(state["reason"]["code"], "HOST_STOP_REENTRY")

    def test_hook_is_silent_without_repository_opt_in(self) -> None:
        other = self.root / "unrelated"
        other.mkdir()
        payload = {"cwd": str(other), "hook_event_name": "Stop", "stop_hook_active": False}
        with working_directory(other):
            self.assertEqual(call_cli(["hook-stop"], payload), (0, "", ""))

    def test_event_or_materialized_state_corruption_fails_closed(self) -> None:
        self.start_rejected_run()
        db = self.root / ".proofed" / "state.db"
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE states SET state_hash=?", ("0" * 64,))
            connection.commit()
        with self.assertRaises(KernelError):
            Kernel(self.root).active_run()


class ConformanceTests(unittest.TestCase):
    def test_runtime_version_matches_distribution_metadata(self) -> None:
        self.assertEqual(__version__, version("proofed-agent"))

    def test_shared_vectors_pass_both_independent_verifiers(self) -> None:
        python = subprocess.run(
            [sys.executable, str(REPO_ROOT / "verifiers/python/check_receipt.py"), str(VECTORS), "--vectors"],
            text=True,
            capture_output=True,
            check=False,
        )
        node = subprocess.run(
            ["node", str(REPO_ROOT / "verifiers/javascript/check-receipt.mjs"), str(VECTORS), "--vectors"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(python.returncode, 0, python.stderr or python.stdout)
        self.assertEqual(node.returncode, 0, node.stderr or node.stdout)

    def test_public_package_surface_stays_small(self) -> None:
        ignored_parts = {".git", ".proofed", "__pycache__", ".pytest_cache", "dist", "build"}
        files = [
            path
            for path in REPO_ROOT.rglob("*")
            if path.is_file()
            and not ignored_parts.intersection(path.parts)
            and "assets" not in path.relative_to(REPO_ROOT).parts
            and not any(part.endswith(".egg-info") for part in path.parts)
        ]
        media = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "assets").glob("*")
            if path.is_file()
        )
        # Distribution surfaces justify two additions beyond the original
        # 30-file alpha budget: a Chinese entry point and PyPI OIDC workflow.
        self.assertLessEqual(len(files), 32)
        self.assertEqual(media, ["assets/proofed-red-green.gif", "assets/proofed-red-green.mp4"])
        self.assertTrue(all((REPO_ROOT / path).stat().st_size <= 5_000_000 for path in media))
        self.assertLessEqual(len((REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()), 70)

    def test_detached_json_cannot_self_assert_ci_trust(self) -> None:
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        bundle = vectors["cases"][0]["bundle"]
        bundle["statements"][0]["predicate"]["producer"]["trustLevel"] = "L1"
        self.assertEqual(verify_bundle(bundle, require_trust="L1"), ["UNVERIFIED_TRUST_CLAIM"])


if __name__ == "__main__":
    unittest.main()
