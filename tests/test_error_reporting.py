"""SENTRY_DSN が .env / 実環境変数のどちらからでも解決され、初期化に渡されることを確認する。"""

import json
import os
import unittest
from unittest import mock

import sentry_sdk

from app import scheduler, sync
from app.error_reporting import init_error_reporting

ENV_FILE_DSN = "https://env-file@example.com/1"
ENVIRON_DSN = "https://environ@example.com/2"


class SentryDsnTest(unittest.TestCase):
    def resolve(self, env_file: dict[str, str], environ: dict[str, str]) -> str | None:
        with mock.patch.dict(os.environ, environ, clear=True), mock.patch.object(
            sync, "load_env_file", return_value=env_file
        ):
            return sync.get_config().get("SENTRY_DSN")

    def test_env_file_only(self):
        self.assertEqual(self.resolve({"SENTRY_DSN": ENV_FILE_DSN}, {}), ENV_FILE_DSN)

    def test_environment_overrides_env_file(self):
        self.assertEqual(self.resolve({"SENTRY_DSN": ENV_FILE_DSN}, {"SENTRY_DSN": ENVIRON_DSN}), ENVIRON_DSN)

    def test_unset(self):
        self.assertIsNone(self.resolve({}, {}))

    def test_init_skips_when_empty_and_passes_dsn(self):
        with mock.patch("app.error_reporting.sentry_sdk.init") as init:
            init_error_reporting(None)
            init.assert_not_called()
            init_error_reporting(ENV_FILE_DSN)
            init.assert_called_once_with(
                dsn=ENV_FILE_DSN, traces_sample_rate=0, data_collection={"stack_frame_variables": False}
            )

    def test_entrypoints_pass_resolved_dsn(self):
        for module in (sync, scheduler):
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "get_config", return_value={"SENTRY_DSN": ENV_FILE_DSN}
            ), mock.patch.object(module, "init_error_reporting") as init, mock.patch.object(
                module, "run_sync", side_effect=KeyboardInterrupt
            ), mock.patch.object(module.logging, "basicConfig"):
                with self.assertRaises(KeyboardInterrupt):
                    module.main()
                init.assert_called_once_with(ENV_FILE_DSN)


class RealSdkTest(unittest.TestCase):
    """モックではなく実際の sentry_sdk で、初期化が落ちず、ローカル変数が送信されないことを確認する。"""

    def tearDown(self):
        sentry_sdk.get_client().close()
        sentry_sdk.init()

    def test_init_succeeds_and_sends_no_frame_variables(self):
        # 秘密値は実行時に組み立てる。ソース行に literal で書くと context_line として送信されうるため。
        secret = "".join(["hun", "ter2"])

        def fail():
            password = secret
            raise ValueError(len(password))

        init_error_reporting(ENV_FILE_DSN)
        transport = sentry_sdk.get_client().transport
        with mock.patch.object(transport, "capture_envelope") as capture:
            try:
                fail()
            except ValueError:
                sentry_sdk.capture_exception()

        envelope = capture.call_args.args[0]
        event = next(item.payload.json for item in envelope.items if item.type == "event")
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertTrue(frames)
        for frame in frames:
            self.assertNotIn("vars", frame)
        self.assertNotIn(secret, json.dumps(event))


if __name__ == "__main__":
    unittest.main()
