from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .techem_api import TechemApiClient


class TechemCoordinator(DataUpdateCoordinator[dict]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: TechemApiClient,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            logger=api.logger,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self.api.fetch_latest_readings)
        except Exception as exc:
            raise UpdateFailed(str(exc)) from exc
