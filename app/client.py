"""OMRON connect クラウドのクライアント (日本アカウント / API v1、Kii ベースのバックエンド)。

先行実装、主に bugficks/omramin の omronconnect.py をもとにリバースエンジニアリングしている。
通信フローの詳細と参考リポジトリは README.md を参照。
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

# ----------------------------------------------------------------------------
# リージョン設定 (日本アカウント -> API v1 / Kii ベースのバックエンド)。
# appID / appKey は、このリージョン向けの公式 OMRON connect モバイルアプリに
# 埋め込まれた共有クライアント認証情報であり、ユーザーごとの秘密情報ではない。
# 出典: bugficks/omramin の data/region_v1.json ("HK", "JP", "KR", "TW" グループ)。
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

# bodyIndexList で使われる ValueType コード (体重・体組成計に関係するものだけ)。
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
    """omronconnect.py の convert_data_util を再現する (value * 10**scale を Decimal で誤差なく計算)。"""

    factor = Decimal("0.1") ** (-scale) if scale < 0 else Decimal(10) ** scale
    return float(Decimal(value) * factor)


def convert_weight_to_kg(weight: float, unit: int) -> float:
    """単位コードに従って、生の体重値を kg に変換する。"""

    if unit == WEIGHT_UNIT_G:
        return weight / 1000
    if unit == WEIGHT_UNIT_LB:
        return weight * 0.45359237
    if unit == WEIGHT_UNIT_ST:
        return weight * 6.35029318
    return weight


class OmronConnectV1:
    """OMRON connect v1 (Kii ベース) クラウドバックエンドのクライアント。"""

    def __init__(self) -> None:
        """アプリ識別用の共通ヘッダーを設定したセッションを作る。"""

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
        """認証し、ベアラートークンをセッションに保持する。"""

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
        """重複を除いたデバイスを dict (deviceCategory, deviceModel, deviceSerialID, userNumberInDevice) で返す。"""

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
                                # プロファイル 0 はデバイス自体でありユーザーではない
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
        """1 つのデバイス / ユーザーについて、`search_date_from` (ミリ秒エポック) 以降の測定値を取得する。

        `search_date_from=0` を渡すと全履歴を取得する。

        measureData エンドポイントは 200 件単位でページングされる。不透明な
        `paginationKey` (観測した形式は "<page>/<pageSize>"、例: "1/200") が
        `returnedValue` の `nextPaginationKey` として返るので、次の要求に渡す。
        これは非公開の挙動で、参照実装の omramin も扱っていないが、実測で確認済み。
        省略すると結果が黙って最初の 200 件で頭打ちになる。
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
    """measureData の生の 1 エントリを、体重・体組成のフラットな行に変換する。"""

    body_index = m.get("bodyIndexList") or {}

    def figure(code: str) -> tuple[float, int] | None:
        """bodyIndexList のエントリを (値, subtype) にデコードする。存在しなければ None。"""

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
        """任意項目のデコード済みの値だけを返す。存在しなければ None。"""

        entry = figure(code)
        return entry[0] if entry else None

    measurement_ms = m.get("measureDateTo")
    tz_name = m.get("timeZone") or "UTC"
    dt_utc = datetime.datetime.fromtimestamp(measurement_ms / 1000, tz=datetime.timezone.utc)
    try:
        dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        # API がホストの tz データベースに無いタイムゾーン名を返すことがある。
        # レコードを捨てずに UTC へフォールバックする。
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
        # CSV_FIELDS には含まれない。同期状態の追跡用の内部値
        "_measurement_ms": measurement_ms,
    }
