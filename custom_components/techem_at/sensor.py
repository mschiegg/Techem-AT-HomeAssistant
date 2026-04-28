from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TechemCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TechemCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [TechemLatestReadingSensor(coordinator, meter) for meter in coordinator.data.get("active_meters", [])]
    )


class TechemLatestReadingSensor(CoordinatorEntity[TechemCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: TechemCoordinator, meter: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._sensor_key = meter["sensor_key"]
        self._device_number = meter.get("device_number")
        self._attr_unique_id = self._sensor_key
        self._attr_name = f"{meter['location_label']} {meter['device_label']}"
        self._attr_native_unit_of_measurement = meter.get("measurement_unit")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.data.get('unit_id')}:{self._device_number}")},
            manufacturer="Techem",
            model=meter.get("device_sub_category"),
            name=f"Techem {meter['location_label']} {meter['device_label']}",
            serial_number=self._device_number,
        )
        if meter.get("measurement_unit") == "m³":
            self._attr_suggested_display_precision = 3

    def _meter(self) -> dict[str, Any] | None:
        for meter in self.coordinator.data.get("active_meters", []):
            if meter.get("sensor_key") == self._sensor_key:
                return meter
        return None

    @property
    def native_value(self) -> Any:
        meter = self._meter()
        return None if meter is None else meter.get("reading")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meter = self._meter() or {}
        return {
            "device_number": meter.get("device_number"),
            "device_type": meter.get("device_type"),
            "device_category": meter.get("device_category"),
            "device_sub_category": meter.get("device_sub_category"),
            "device_label": meter.get("device_label"),
            "location": meter.get("location_label"),
            "reading_date": meter.get("reading_date"),
            "reading_iso8601": meter.get("reading_iso8601"),
            "factor": meter.get("factor"),
            "percentage": meter.get("percentage"),
            "unit_id": self.coordinator.data.get("unit_id"),
            "resident_name": self.coordinator.data.get("resident_name"),
        }
