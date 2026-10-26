"""未配送レコード outbox の永続化と重複排除のテスト。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import outbox


def _row(measured_at: str, serial: str = "SN1", user: int = 1) -> dict:
    """テスト用の最小レコードを作る。"""

    return {
        "measured_at_utc": measured_at,
        "device_serial": serial,
        "user_number_in_device": user,
        "weight_kg": 60.0,
    }


class OutboxTest(unittest.TestCase):
    """outbox の読み書きと enqueue の挙動を検証する。"""

    def test_load_pending_returns_empty_when_file_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(outbox.load_pending(Path(tmp) / "outbox.json"), [])

    def test_save_then_load_round_trips_rows(self):
        rows = [_row("2026-01-01T00:00:00+00:00")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outbox.json"
            outbox.save_pending(path, rows)
            self.assertEqual(outbox.load_pending(path), rows)

    def test_enqueue_skips_rows_already_pending_and_keeps_inputs_intact(self):
        first = _row("2026-01-01T00:00:00+00:00")
        second = _row("2026-01-02T00:00:00+00:00")
        pending = [first]
        new_rows = [dict(first), second]

        result = outbox.enqueue(pending, new_rows)

        self.assertEqual(result, [first, second])
        self.assertEqual(pending, [first])
        self.assertEqual(new_rows, [first, second])
        self.assertEqual(outbox.enqueue(result, new_rows), [first, second])

    def test_enqueue_matches_rows_after_json_round_trip(self):
        row = _row("2026-01-01T00:00:00+00:00")
        restored = json.loads(json.dumps([row]))
        self.assertEqual(outbox.enqueue(restored, [row]), restored)

    def test_load_pending_raises_on_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outbox.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                outbox.load_pending(path)


if __name__ == "__main__":
    unittest.main()
