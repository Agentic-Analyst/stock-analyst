from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from llms.config import LLMProvider
from security.llm_cache import cache_key_for_request, configure_llm_cache


class LLMCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_llm_cache(enabled=False, cache_dir=None)

    def test_cache_key_is_stable(self) -> None:
        messages = [{"role": "user", "content": "Reply with OK."}]
        first = cache_key_for_request(
            model_name="demo-model",
            messages=messages,
            temperature=0.1,
        )
        second = cache_key_for_request(
            model_name="demo-model",
            messages=messages,
            temperature=0.1,
        )
        self.assertEqual(first, second)

    def test_provider_uses_disk_cache(self) -> None:
        calls = {"count": 0}

        def fake_model(messages, temperature=0.3):
            calls["count"] += 1
            return "cached-response", 0.42

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"DUMMY_KEY": "present"},
            clear=False,
        ), patch.dict(
            LLMProvider.MODELS,
            {"dummy-model": {"function": fake_model, "api_key": "DUMMY_KEY"}},
            clear=False,
        ):
            configure_llm_cache(enabled=True, cache_dir=tmp_dir)
            provider = LLMProvider("dummy-model")

            first_response, first_cost = provider(
                [{"role": "user", "content": "Reply with OK."}],
                temperature=0.1,
            )
            second_response, second_cost = provider(
                [{"role": "user", "content": "Reply with OK."}],
                temperature=0.1,
            )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(first_response, "cached-response")
        self.assertEqual(second_response, "cached-response")
        self.assertEqual(first_cost, 0.42)
        self.assertEqual(second_cost, 0.0)


if __name__ == "__main__":
    unittest.main()
