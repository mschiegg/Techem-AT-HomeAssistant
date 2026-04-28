#!/usr/bin/env python3
from __future__ import annotations

import argparse
import codecs
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

BASE_URL = "https://kundenportal.techem.at"
UNITS_ENDPOINT = "/o/rest/resident/list-for-user"
METER_DEVICE_ENDPOINT = "/o/rest/meter-device/list"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON_ACCEPT = "application/json, text/plain, */*"
LOCATION_LABELS = {
    "modules.rooms.storageRoom": "Abstellraum",
    "modules.rooms.kitchen": "Kueche",
    "modules.rooms.bath": "Bad",
}
DEVICE_LABELS = {
    "HEAT_METER": "Heizung",
    "HEAT_METER_WITH_RADIO": "Heizung",
    "WARM_WATER_METER": "Warmwasser",
    "WARM_WATER_METER_WITH_RADIO": "Warmwasser",
}


class TechemAuthError(Exception):
    """Raised when login fails."""


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def ensure_credentials() -> tuple[str, str]:
    email = os.environ.get("TECHEM_EMAIL")
    password = os.environ.get("TECHEM_PASSWORD")
    if not email or not password:
        raise RuntimeError("TECHEM_EMAIL und TECHEM_PASSWORD fehlen in .env.")
    return email, password


def relevant_cookies(session: requests.Session) -> dict[str, str]:
    prefixes = ("JSESSIONID", "COOKIE_SUPPORT", "GUEST_LANGUAGE_ID", "LFR_SESSION_STATE_")
    return {
        name: value
        for name, value in session.cookies.get_dict().items()
        if name in prefixes or name.startswith(prefixes[-1])
    }


def response_preview(response: requests.Response, limit: int = 300) -> str:
    return response.text[:limit].replace("\n", "\\n").replace("\r", "\\r")


def debug_response(debug: bool, label: str, response: requests.Response, session: requests.Session) -> None:
    if not debug:
        return
    print(f"\n=== {label} ===")
    print(f"URL: {response.url}")
    print(f"Status: {response.status_code}")
    print(f"Redirects: {[item.status_code for item in response.history]}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    print(f"Cookies: {relevant_cookies(session)}")
    print(f"Preview: {response_preview(response)}")


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class TechemExporter:
    def __init__(self, email: str, password: str, debug: bool = False, timeout: int = 30) -> None:
        self.email = email
        self.password = password
        self.debug = debug
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
            }
        )

    def export(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        devices_page = self._login_and_load_devices_page()
        auth_token = self._require_auth_token(devices_page)
        units = self._api_get(
            endpoint=UNITS_ENDPOINT,
            params={"p_auth": auth_token},
            referer=devices_page.url,
            label="Units API",
        )
        if not isinstance(units, list) or not units:
            raise RuntimeError("Keine Einheit in der Units-Response gefunden.")

        primary_unit = units[0]
        unit_id = primary_unit.get("unitId")
        if not unit_id:
            raise RuntimeError("unitId fehlt in der Units-Response.")

        meter_devices = self._api_get(
            endpoint=METER_DEVICE_ENDPOINT,
            params={"unit_id": unit_id, "p_auth": auth_token},
            referer=devices_page.url,
            label="Meter Device API",
        )
        latest_readings = self._normalize_latest_readings(
            meter_devices_payload=meter_devices,
            unit_id=unit_id,
            resident_name=primary_unit.get("name"),
        )
        return units, meter_devices, latest_readings

    def _login_and_load_devices_page(self) -> requests.Response:
        login_page = self.session.get(
            urljoin(BASE_URL, "/devices"),
            headers=self._build_headers(urljoin(BASE_URL, "/"), accept=HTML_ACCEPT),
            allow_redirects=True,
            timeout=self.timeout,
        )
        debug_response(self.debug, "Devices/Login page", login_page, self.session)

        action = self._parse_login_action(login_page.text)
        form = self._parse_login_form(login_page.text)
        if not action:
            raise TechemAuthError("Login-Action konnte nicht ermittelt werden.")

        payload = dict(form["fields"])
        payload[form["login_field"]] = self.email
        payload[form["password_field"]] = self.password

        remember_me_field = next((field for field in payload if field.endswith("_rememberMe")), None)
        if remember_me_field:
            payload[remember_me_field] = "true"

        login_response = self.session.post(
            urljoin(BASE_URL, action),
            data=payload,
            headers=self._build_headers(login_page.url, accept=HTML_ACCEPT),
            allow_redirects=True,
            timeout=self.timeout,
        )
        debug_response(self.debug, "Login POST", login_response, self.session)

        if "loginForm" in login_response.text:
            raise TechemAuthError("Login fehlgeschlagen.")

        if "/devices" not in login_response.url:
            login_response = self.session.get(
                urljoin(BASE_URL, "/devices"),
                headers=self._build_headers(login_response.url, accept=HTML_ACCEPT),
                timeout=self.timeout,
            )
            debug_response(self.debug, "Authenticated devices page", login_response, self.session)

        if "loginForm" in login_response.text:
            raise TechemAuthError("Devices-Seite wurde nach dem Login nicht authentifiziert geladen.")
        return login_response

    def _require_auth_token(self, response: requests.Response) -> str:
        auth_token = self._parse_liferay_auth_token(response.text)
        if auth_token:
            return auth_token

        refreshed = self.session.get(
            urljoin(BASE_URL, "/devices"),
            headers=self._build_headers(response.url, accept=HTML_ACCEPT),
            timeout=self.timeout,
        )
        debug_response(self.debug, "Refresh devices page", refreshed, self.session)
        auth_token = self._parse_liferay_auth_token(refreshed.text)
        if not auth_token:
            raise RuntimeError("Liferay authToken fehlt nach dem Login.")
        return auth_token

    def _api_get(
        self,
        endpoint: str,
        params: dict[str, Any],
        referer: str,
        label: str,
    ) -> Any:
        response = self.session.get(
            urljoin(BASE_URL, endpoint),
            params=params,
            headers=self._build_headers(referer, accept=JSON_ACCEPT),
            timeout=self.timeout,
        )
        debug_response(self.debug, label, response, self.session)

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{endpoint} lieferte kein JSON.") from exc

        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("errorcode")):
            raise RuntimeError(f"{endpoint} fehlgeschlagen: {payload}")
        return payload

    def _build_headers(self, referer: str, accept: str) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer,
            "Origin": BASE_URL,
        }
        if "json" in accept:
            headers.update(
                {
                    "X-Requested-With": "XMLHttpRequest",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                }
            )
        return headers

    def _parse_liferay_auth_token(self, html: str) -> str | None:
        match = re.search(r"Liferay\.authToken\s*=\s*'([^']+)'", html)
        return match.group(1) if match else None

    def _parse_login_action(self, html: str) -> str | None:
        match = re.search(r"form\.action\s*=\s*'([^']+)'", html)
        if not match:
            return None
        return codecs.decode(match.group(1), "unicode_escape")

    def _parse_login_form(self, html: str) -> dict[str, Any]:
        form_match = re.search(
            r'(<form[^>]+id="([^"]*loginForm[^"]*)"[^>]*>(.*?)</form>)',
            html,
            re.DOTALL,
        )
        if not form_match:
            raise TechemAuthError("Login-Formular konnte nicht gefunden werden.")

        fields: dict[str, str] = {}
        login_field = None
        password_field = None

        for attrs in re.findall(r"<input\b([^>]+)>", form_match.group(1), re.DOTALL):
            name_match = re.search(r'\bname="([^"]+)"', attrs)
            if not name_match:
                continue

            name = name_match.group(1)
            value_match = re.search(r'\bvalue="([^"]*)"', attrs)
            input_type_match = re.search(r'\btype="([^"]+)"', attrs)
            input_type = input_type_match.group(1).lower() if input_type_match else "text"

            fields[name] = value_match.group(1) if value_match else ""
            if input_type == "text" and name.endswith("_login"):
                login_field = name
            if input_type == "password" and name.endswith("_password"):
                password_field = name

        if not login_field or not password_field:
            raise TechemAuthError("Login- oder Passwort-Feld fehlt.")

        return {
            "fields": fields,
            "login_field": login_field,
            "password_field": password_field,
        }

    def _normalize_latest_readings(
        self,
        meter_devices_payload: Any,
        unit_id: str,
        resident_name: str | None,
    ) -> dict[str, Any]:
        active_meters = []

        for item in meter_devices_payload or []:
            meter = self._extract_active_meter(item)
            if not meter:
                continue

            last_reading = item.get("lastReading") or {}
            location_label = LOCATION_LABELS.get(item.get("location") or "", item.get("location") or "Unbekannt")
            device_sub_category = (
                meter.get("deviceSubCategory")
                or meter.get("deviceCategory")
                or item.get("type")
                or "meter"
            )
            device_label = DEVICE_LABELS.get(
                device_sub_category,
                device_sub_category.replace("_", " ").title(),
            )
            device_number = (
                item.get("geraetenummer1")
                or last_reading.get("geraetenummer1")
                or meter.get("geraetenummer1")
            )
            reading_iso = self._timestamp_ms_to_iso8601(last_reading.get("readingDate"))

            active_meters.append(
                {
                    "sensor_key": self._slugify(
                        f"techem_{location_label}_{device_sub_category}_{device_number}"
                    ),
                    "device_number": device_number,
                    "device_type": item.get("type"),
                    "device_category": meter.get("deviceCategory"),
                    "device_sub_category": device_sub_category,
                    "device_label": device_label,
                    "location_label": location_label,
                    "measurement_unit": meter.get("measurementUnit"),
                    "reading": last_reading.get("reading"),
                    "reading_date": reading_iso[:10] if reading_iso else None,
                    "reading_iso8601": reading_iso,
                    "factor": item.get("factor"),
                    "percentage": item.get("percentage"),
                }
            )

        return {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "unit_id": unit_id,
            "resident_name": resident_name,
            "active_meter_count": len(active_meters),
            "active_meters": active_meters,
        }

    def _extract_active_meter(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        meters = item.get("listOfMeters") or []
        if not meters or not isinstance(meters[0], dict):
            return None
        meter = meters[0]
        if not meter.get("aktiv"):
            return None
        return meter

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower())
        return slug.strip("_")

    def _timestamp_ms_to_iso8601(self, timestamp_ms: Any) -> str | None:
        if timestamp_ms in (None, ""):
            return None
        return dt.datetime.fromtimestamp(
            int(timestamp_ms) / 1000,
            tz=dt.timezone.utc,
        ).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exportiert aktuelle Techem-Zaehlerstaende aus der Devices-Ansicht.",
    )
    parser.add_argument("--debug", action="store_true", help="HTTP-Debug-Ausgaben aktivieren")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(".env"))

    try:
        email, password = ensure_credentials()
        exporter = TechemExporter(email=email, password=password, debug=args.debug)
        units, meter_devices, latest_readings = exporter.export()
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    save_json(Path("techem_units.json"), units)
    save_json(Path("techem_devices_raw.json"), meter_devices)
    save_json(Path("techem_latest_readings.json"), latest_readings)

    print("Gespeichert:")
    print("- techem_units.json")
    print("- techem_devices_raw.json")
    print("- techem_latest_readings.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
