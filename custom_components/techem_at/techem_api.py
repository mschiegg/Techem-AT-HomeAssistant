from __future__ import annotations

import codecs
import datetime as dt
import logging
import re
from typing import Any
from urllib.parse import urljoin

import requests

from .const import BASE_URL, METER_DEVICE_ENDPOINT, UNITS_ENDPOINT, USER_AGENT

JSON_ACCEPT = "application/json, text/plain, */*"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
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

_LOGGER = logging.getLogger(__name__)


class TechemAuthError(Exception):
    """Raised when Techem login fails."""


class TechemApiClient:
    def __init__(self, email: str, password: str, timeout: int = 30) -> None:
        self.email = email
        self.password = password
        self.timeout = timeout
        self.logger = _LOGGER

    def fetch_latest_readings(self) -> dict[str, Any]:
        session = self._create_session()
        devices_page = self._login_and_load_devices_page(session)
        auth_token = self._require_auth_token(session, devices_page)
        unit = self._fetch_primary_unit(session, devices_page["url"], auth_token)
        unit_id = unit.get("unitId")
        if not unit_id:
            raise RuntimeError("unitId fehlt in der Units-Response.")

        meter_devices = self._api_get(
            session=session,
            endpoint=METER_DEVICE_ENDPOINT,
            params={"unit_id": unit_id, "p_auth": auth_token},
            referer=devices_page["url"],
        )
        return self._normalize_latest_readings(
            meter_devices_payload=meter_devices,
            unit_id=unit_id,
            resident_name=unit.get("name"),
        )

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
            }
        )
        return session

    def _login_and_load_devices_page(self, session: requests.Session) -> dict[str, str]:
        login_page = session.get(
            urljoin(BASE_URL, "/devices"),
            headers=self._build_headers(urljoin(BASE_URL, "/"), accept=HTML_ACCEPT),
            allow_redirects=True,
            timeout=self.timeout,
        )
        form = self._parse_login_form(login_page.text)
        action = self._parse_login_action(login_page.text)
        if not action:
            raise TechemAuthError("Login-Action konnte nicht ermittelt werden.")

        payload = dict(form["fields"])
        payload[form["login_field"]] = self.email
        payload[form["password_field"]] = self.password

        remember_me_field = next((field for field in payload if field.endswith("_rememberMe")), None)
        if remember_me_field:
            payload[remember_me_field] = "true"

        login_response = session.post(
            urljoin(BASE_URL, action),
            data=payload,
            headers=self._build_headers(login_page.url, accept=HTML_ACCEPT),
            allow_redirects=True,
            timeout=self.timeout,
        )
        if "loginForm" in login_response.text:
            raise TechemAuthError("Login fehlgeschlagen.")

        if "/devices" not in login_response.url:
            login_response = session.get(
                urljoin(BASE_URL, "/devices"),
                headers=self._build_headers(login_response.url, accept=HTML_ACCEPT),
                timeout=self.timeout,
            )

        if "loginForm" in login_response.text:
            raise TechemAuthError("Devices-Seite wurde nach dem Login nicht authentifiziert geladen.")

        return {"html": login_response.text, "url": login_response.url}

    def _require_auth_token(self, session: requests.Session, devices_page: dict[str, str]) -> str:
        auth_token = self._parse_liferay_auth_token(devices_page["html"])
        if auth_token:
            return auth_token

        refreshed_page = session.get(
            urljoin(BASE_URL, "/devices"),
            headers=self._build_headers(devices_page["url"], accept=HTML_ACCEPT),
            timeout=self.timeout,
        )
        auth_token = self._parse_liferay_auth_token(refreshed_page.text)
        if not auth_token:
            raise TechemAuthError("Liferay authToken fehlt nach dem Login.")
        devices_page["html"] = refreshed_page.text
        devices_page["url"] = refreshed_page.url
        return auth_token

    def _fetch_primary_unit(
        self,
        session: requests.Session,
        referer: str,
        auth_token: str,
    ) -> dict[str, Any]:
        units = self._api_get(
            session=session,
            endpoint=UNITS_ENDPOINT,
            params={"p_auth": auth_token},
            referer=referer,
        )
        if not isinstance(units, list) or not units:
            raise RuntimeError("Keine Einheit in der Units-Response gefunden.")

        unit = units[0]
        if not isinstance(unit, dict):
            raise RuntimeError("Units-Response hat ein unerwartetes Format.")
        return unit

    def _api_get(
        self,
        session: requests.Session,
        endpoint: str,
        params: dict[str, Any],
        referer: str,
    ) -> Any:
        response = session.get(
            urljoin(BASE_URL, endpoint),
            params=params,
            headers=self._build_headers(referer, accept=JSON_ACCEPT),
            timeout=self.timeout,
        )

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
            location_label = self._location_label(item.get("location"))
            device_sub_category = (
                meter.get("deviceSubCategory")
                or meter.get("deviceCategory")
                or item.get("type")
                or "meter"
            )
            device_label = self._device_label(device_sub_category)
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
        if not meters:
            return None

        meter = meters[0]
        if not isinstance(meter, dict) or not meter.get("aktiv"):
            return None
        return meter

    def _location_label(self, location_key: str | None) -> str:
        return LOCATION_LABELS.get(location_key or "", location_key or "Unbekannt")

    def _device_label(self, device_key: str | None) -> str:
        if not device_key:
            return "Zaehler"
        if device_key in DEVICE_LABELS:
            return DEVICE_LABELS[device_key]
        return device_key.replace("_", " ").title()

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
