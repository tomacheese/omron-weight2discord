"""
OMRON connect cloud client (Japan account / API v1, Kii-based backend).

Reverse-engineered from prior-art projects, primarily bugficks/omramin's
omronconnect.py. See README.md for the full flow writeup and references.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

# ----------------------------------------------------------------------------
# Region configuration (Japan account -> API v1 / Kii-based backend).
# appID/appKey are the shared client credentials baked into the official
# OMRON connect mobile app for this region; not per-user secrets.
# Source: bugficks/omramin data/region_v1.json ("HK", "JP", "KR", "TW" group).
# ----------------------------------------------------------------------------
SERVER = "https://data-jp.omronconnect.com/api"
APP_ID = "1e3ddd17"
APP_KEY = "b576cf704409ec86facdacc16fbaadad"
COUNTRY = "JP"

OGSC_APP_VERSION = "011.004.00000"
OGSC_SDK_VERSION = "000.005"
USER_AGENT = f"OmronConnect/{OGSC_APP_VERSION}.001 CFNetwork/1335.0.3.4 Darwin/21.6.0)"

APP_URL = f"{SERVER}/apps/{APP_ID}/server-code"

DEVICE_CATEGORY_BPM = "0"
DEVICE_CATEGORY_SCALE = "1"

# ValueType codes used in bodyIndexList (subset relevant to weight/body-composition scales).
VT_KG_FIGURE = "257"
VT_BODY_FAT_PER_FIGURE = "259"
VT_BASAL_METABOLISM_FIGURE = "260"
VT_RATE_SKELETAL_MUSCLE_FIGURE = "261"
VT_BIOLOGICAL_AGE_FIGURE = "263"
VT_VISCERAL_FAT_FIGURE = "264"
VT_BMI_FIGURE = "262"

WEIGHT_UNIT_G = 8192
WEIGHT_UNIT_KG = 8195
WEIGHT_UNIT_LB = 8208
WEIGHT_UNIT_ST = 8224

CSV_FIELDS = [
    "measured_at_utc",
    "measured_at_local",
    "timezone",
    "weight_kg",
    "bmi",
    "body_fat_percentage",
    "skeletal_muscle_percentage",
    "resting_metabolism_kcal",
    "visceral_fat_level",
    "metabolic_age",
    "device_model",
    "device_serial",
    "user_number_in_device",
]


def convert_data_util(value: int, scale: int) -> float:
    """Reproduce omronconnect.py's convert_data_util (value * 10**scale, decimal-safe)."""

    factor = Decimal("0.1") ** (-scale) if scale < 0 else Decimal(10) ** scale
    return float(Decimal(value) * factor)


def convert_weight_to_kg(weight: float, unit: int) -> float:
    """Convert a raw weight figure to kilograms based on its unit code."""

    if unit == WEIGHT_UNIT_G:
        return weight / 1000
    if unit == WEIGHT_UNIT_LB:
        return weight * 0.45359237
    if unit == WEIGHT_UNIT_ST:
        return weight * 6.35029318
    return weight


class OmronConnectV1:
    """Client for the OMRON connect v1 (Kii-based) cloud backend."""

    def __init__(self) -> None:
        """Create a session preloaded with the shared app-identity headers."""

        self._session = requests.Session()
        self._session.headers.update(
            {
                "user-agent": USER_AGENT,
                "X-OGSC-SDK-Version": OGSC_SDK_VERSION,
                "X-OGSC-App-Version": OGSC_APP_VERSION,
                "X-Kii-AppID": APP_ID,
                "X-Kii-AppKey": APP_KEY,
            }
        )

    def login(self, email: str, password: str) -> None:
        """Authenticate and store the bearer token on the session."""

        r = self._session.post(
            f"{SERVER}/oauth2/token",
            json={"username": email, "password": password},
        )
        r.raise_for_status()
        resp = r.json()
        try:
            access_token = resp["access_token"]
        except KeyError as exc:
            raise RuntimeError(f"login failed, unexpected response: {resp}") from exc

        self._session.headers["authorization"] = f"Bearer {access_token}"

    def get_registered_devices(self) -> list[dict[str, Any]]:
        """Return unique devices as dicts: deviceCategory, deviceModel, deviceSerialID, userNumberInDevice."""

        sync_list: list[dict[str, Any]] = []
        last_sync_date = 0

        while True:
            r = self._session.post(
                f"{APP_URL}/versions/current/synchronizeDeviceConfData",
                json={"countOnlyFlag": 0, "lastSyncDate": last_sync_date},
            )
            r.raise_for_status()
            returned = r.json().get("returnedValue", {}) or {}
            sync_list.extend(returned.get("syncList", []) or [])

            next_key = int(returned.get("nextPaginationKey", 0) or 0)
            if not next_key or next_key == last_sync_date:
                break
            last_sync_date = next_key

        devices: dict[str, dict[str, Any]] = {}
        for sync in sync_list:
            for cat in sync.get("deviceCategoryList", []) or []:
                for model in cat.get("deviceModelList", []) or []:
                    for dev in model.get("deviceSerialIDList", []) or []:
                        try:
                            if str(dev.get("userNumberInDevice")) == "0":
                                # profile 0 is the device itself, not a user
                                continue
                            key = f"{dev['deviceSerialID']}:{dev['userNumberInDevice']}"
                            devices.setdefault(
                                key,
                                {
                                    "deviceCategory": cat.get("deviceCategory"),
                                    "deviceModel": model.get("deviceModel"),
                                    "deviceSerialID": dev["deviceSerialID"],
                                    "userNumberInDevice": dev["userNumberInDevice"],
                                },
                            )
                        except KeyError:
                            continue

        return list(devices.values())

    def get_measurements(self, device: dict[str, Any], search_date_from: int = 0) -> list[dict[str, Any]]:
        """Fetch stored measurements for one device/user from `search_date_from` (ms epoch) onward.

        Pass `search_date_from=0` for full history.

        The measureData endpoint paginates in batches of 200 via an opaque
        `paginationKey` (observed format "<page>/<pageSize>", e.g. "1/200")
        echoed back as `nextPaginationKey` in `returnedValue`. This isn't
        documented and isn't handled by the omramin reference implementation,
        but was confirmed empirically: omitting it silently truncates results
        to only the first 200 records.
        """

        search_date_to = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        base_payload = {
            "containCorrectedDataFlag": 1,
            "containAllDataTypeFlag": 1,
            "deviceCategory": device["deviceCategory"],
            "deviceSerialID": device["deviceSerialID"],
            "userNumberInDevice": int(device["userNumberInDevice"]),
            "searchDateFrom": max(search_date_from, 0),
            "searchDateTo": search_date_to,
        }

        results: list[dict[str, Any]] = []
        pagination_key: str | None = None
        while True:
            payload = dict(base_payload)
            if pagination_key:
                payload["paginationKey"] = pagination_key

            r = self._session.post(f"{APP_URL}/versions/current/measureData", json=payload)
            r.raise_for_status()
            returned = r.json().get("returnedValue")
            if isinstance(returned, list):
                returned = returned[0] if returned else None
            if not returned or "errorCode" in returned:
                break

            page_had_data = False
            for dev_model in returned.get("deviceModelList") or []:
                for dev in dev_model.get("deviceSerialIDList") or []:
                    if dev.get("deviceSerialID") != device["deviceSerialID"]:
                        continue
                    measure_list = dev.get("measureList") or []
                    results.extend(measure_list)
                    page_had_data = page_had_data or bool(measure_list)

            next_key = returned.get("nextPaginationKey")
            if not next_key or not page_had_data:
                break
            pagination_key = next_key

        return results


def parse_scale_measurement(m: dict[str, Any], device: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one raw measureData entry into a flat weight/body-composition row."""

    body_index = m.get("bodyIndexList") or {}

    def figure(code: str) -> tuple[float, int] | None:
        """Decode a bodyIndexList entry into (value, subtype), or None if absent."""

        entry = body_index.get(code)
        if entry is None:
            return None
        value, subtype, scale, _measurement_id = entry
        return convert_data_util(int(value), int(scale)), int(subtype)

    weight_entry = figure(VT_KG_FIGURE)
    if weight_entry is None:
        return None
    weight, weight_unit = weight_entry
    weight = convert_weight_to_kg(weight, weight_unit)

    def optional(code: str) -> float | None:
        """Return only the decoded value for an optional figure, if present."""

        entry = figure(code)
        return entry[0] if entry else None

    measurement_ms = m.get("measureDateTo")
    tz_name = m.get("timeZone") or "UTC"
    dt_utc = datetime.datetime.fromtimestamp(measurement_ms / 1000, tz=datetime.timezone.utc)
    try:
        dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        # The API occasionally reports a timezone name the host's tz database
        # doesn't know; fall back to UTC rather than dropping the record.
        dt_local = dt_utc

    return {
        "measured_at_utc": dt_utc.isoformat(),
        "measured_at_local": dt_local.isoformat(),
        "timezone": tz_name,
        "weight_kg": round(weight, 2),
        "bmi": optional(VT_BMI_FIGURE),
        "body_fat_percentage": optional(VT_BODY_FAT_PER_FIGURE),
        "skeletal_muscle_percentage": optional(VT_RATE_SKELETAL_MUSCLE_FIGURE),
        "resting_metabolism_kcal": optional(VT_BASAL_METABOLISM_FIGURE),
        "visceral_fat_level": optional(VT_VISCERAL_FAT_FIGURE),
        "metabolic_age": optional(VT_BIOLOGICAL_AGE_FIGURE),
        "device_model": device.get("deviceModel"),
        "device_serial": device.get("deviceSerialID"),
        "user_number_in_device": device.get("userNumberInDevice"),
        # not part of CSV_FIELDS, used internally for state tracking
        "_measurement_ms": measurement_ms,
    }
