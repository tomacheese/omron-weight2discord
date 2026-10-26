"""Discord 配送失敗後の再送 (outbox) を `run_sync()` 経由で検証する。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from app import csv_store, sync

WEBHOOK = "https://discord.example/api/webhooks/test"
DEVICE = {
    "deviceSerialID": "SN1",
    "userNumberInDevice": 1,
    "deviceCategory": "1",
    "deviceModel": "HBF-TEST",
}
ROW = {
    "measured_at_utc": "2026-01-01T00:00:00+00:00",
    "measured_at_local": "2026-01-01T09:00:00+09:00",
    "timezone": "Asia/Tokyo",
    "weight_kg": 60.5,
    "bmi": "",
    "body_fat_percentage": "",
    "skeletal_muscle_percentage": "",
    "resting_metabolism_kcal": "",
    "visceral_fat_level": "",
    "metabolic_age": "",
    "device_model": "HBF-TEST",
    "device_serial": "SN1",
    "user_number_in_device": 1,
    "_measurement_ms": 1767225600000,
}


def _response(status: int) -> requests.Response:
    """指定ステータスの Response を作る。"""

    r = requests.Response()
    r.status_code = status
    return r


class FakeClient:
    """OmronConnectV1 の代替。`measurements` が空でなければ 1 件返す。"""

    measurements: list[dict] = []

    def login(self, email, password):
        pass

    def get_registered_devices(self):
        return [DEVICE]

    def get_measurements(self, device, search_date_from=0):
        return list(self.measurements)


class RunSyncOutboxTest(unittest.TestCase):
    """送信失敗後の再実行で未通知レコードが再送されることを検証する。"""

    def _run(self, data_dir: Path, *, webhook: str | None = WEBHOOK, fresh: bool):
        FakeClient.measurements = [{"raw": 1}] if fresh else []
        config = {"OMRON_CONNECT_EMAIL": "a@example.com", "OMRON_CONNECT_PASSWORD": "pw"}
        if webhook:
            config["DISCORD_WEBHOOK"] = webhook
        return mock.patch.multiple(
            sync,
            get_config=mock.Mock(return_value=config),
            OmronConnectV1=FakeClient,
            parse_scale_measurement=mock.Mock(return_value=dict(ROW)),
        )

    def _assert_failure_then_retry(self, failure):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with self._run(data_dir, fresh=True), mock.patch(
                "app.discord_notify.requests.post", side_effect=failure
            ):
                with self.assertRaises(type(failure) if isinstance(failure, Exception) else Exception):
                    sync.run_sync(data_dir)

            self.assertEqual(len(csv_store.load_existing(data_dir / "weight_data.csv")), 1)
            state = json.loads((data_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["SN1:1"]["last_synced_ms"], ROW["_measurement_ms"])
            pending = json.loads((data_dir / "outbox.json").read_text(encoding="utf-8"))["pending"]
            self.assertEqual([r["measured_at_utc"] for r in pending], [ROW["measured_at_utc"]])

            with self._run(data_dir, fresh=False), mock.patch(
                "app.discord_notify.requests.post", return_value=_response(204)
            ) as post:
                sync.run_sync(data_dir)

            post.assert_called_once()
            embeds = post.call_args.kwargs["json"]["embeds"]
            self.assertEqual([e["timestamp"] for e in embeds], [ROW["measured_at_utc"]])
            self.assertEqual(
                json.loads((data_dir / "outbox.json").read_text(encoding="utf-8")), {"pending": []}
            )

    def test_http_500_is_resent_on_next_run(self):
        self._assert_failure_then_retry(requests.HTTPError("500 Server Error"))

    def test_timeout_is_resent_on_next_run(self):
        self._assert_failure_then_retry(requests.Timeout("timed out"))

    def test_http_500_response_raises_http_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with self._run(data_dir, fresh=True), mock.patch(
                "app.discord_notify.requests.post", return_value=_response(500)
            ):
                with self.assertRaises(requests.HTTPError):
                    sync.run_sync(data_dir)
            self.assertEqual(len(json.loads((data_dir / "outbox.json").read_text(encoding="utf-8"))["pending"]), 1)

    def test_no_outbox_without_webhook(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with self._run(data_dir, webhook=None, fresh=True):
                sync.run_sync(data_dir)
            self.assertFalse((data_dir / "outbox.json").exists())


if __name__ == "__main__":
    unittest.main()
