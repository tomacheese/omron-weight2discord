"""OMRON への全リクエストに timeout を指定し、timeout 後も scheduler が継続することを検証する。"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from app import scheduler
from app.client import REQUEST_TIMEOUT, OmronConnectV1

DEVICE = {"deviceCategory": "0", "deviceSerialID": "SN1", "userNumberInDevice": "1"}


class RequestTimeoutTest(unittest.TestCase):
    def _client(self, returned):
        client = OmronConnectV1()
        response = mock.Mock()
        response.json.return_value = returned
        client._session = mock.MagicMock()
        client._session.post.return_value = response
        return client

    def test_login_passes_timeout(self):
        client = self._client({"access_token": "t"})
        client.login("a@example.com", "pw")
        self.assertEqual(client._session.post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_get_registered_devices_passes_timeout(self):
        client = self._client({"returnedValue": {}})
        client.get_registered_devices()
        self.assertEqual(client._session.post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_get_measurements_passes_timeout(self):
        client = self._client({"returnedValue": None})
        client.get_measurements(DEVICE)
        self.assertEqual(client._session.post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)


class SchedulerTimeoutTest(unittest.TestCase):
    def test_timeout_does_not_stop_next_pass(self):
        sync = mock.Mock(side_effect=[requests.exceptions.ReadTimeout("slow"), None])
        sleeps = mock.Mock(side_effect=[None, SystemExit(0)])
        with mock.patch.object(scheduler, "run_sync", sync), mock.patch.object(
            scheduler.time, "sleep", sleeps
        ), mock.patch.object(scheduler, "init_error_reporting"), self.assertLogs(
            "app.scheduler", level="ERROR"
        ), self.assertRaises(SystemExit):
            scheduler.main()
        self.assertEqual(sync.call_count, 2)


if __name__ == "__main__":
    unittest.main()
