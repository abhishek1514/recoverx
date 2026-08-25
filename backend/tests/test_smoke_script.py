"""Unit test for automated smoke test script."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.main import app
from scripts.smoke_test import run_smoke_test


class SmokeScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def test_smoke_test_execution_against_testclient(self) -> None:
        with patch("scripts.smoke_test.httpx.Client", return_value=self.client):
            result = run_smoke_test("http://testserver")
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()

