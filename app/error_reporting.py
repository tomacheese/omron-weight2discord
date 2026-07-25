"""Shared GlitchTip (Sentry-compatible) error reporting setup for both entrypoints."""

from __future__ import annotations

import os

import sentry_sdk


def init_error_reporting() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured; no-op otherwise.

    Mirrors the DISCORD_WEBHOOK pattern: an optional setting that's skipped
    entirely when unset. traces_sample_rate=0 disables performance tracing
    since this is an always-running sync batch, not a request-serving app.
    """

    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0)
