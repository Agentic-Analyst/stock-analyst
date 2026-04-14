from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from security.calibrate_directions import choose_target_direction


class CalibrationTests(unittest.TestCase):
    def test_choose_bearish_when_clean_case_is_strong_buy(self) -> None:
        direction, details = choose_target_direction(
            {"rating": "STRONG BUY", "expected_return_pct_12m": 28.65}
        )
        self.assertEqual(direction, "bearish")
        self.assertIsNone(details["distance_to_bullish_band"])

    def test_choose_nearest_boundary_for_hold_case(self) -> None:
        direction, details = choose_target_direction(
            {"rating": "HOLD", "expected_return_pct_12m": 4.82}
        )
        self.assertEqual(direction, "bullish")
        self.assertLess(
            float(details["distance_to_bullish_band"]),
            float(details["distance_to_bearish_band"]),
        )


if __name__ == "__main__":
    unittest.main()
