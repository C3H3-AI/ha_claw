from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from ..const import DOMAIN, VERSION

_URL_PATH = f"/api/{DOMAIN}/ha_crack.js"
_MODULE_URL = f"{_URL_PATH}?v={VERSION}"
_DATA_KEY = "frontend_loader"


async def async_setup_frontend_loader(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_KEY):
        return

    js_path = Path(__file__).parents[1] / "www" / "ha_crack.js"
    media_path = Path(__file__).parents[1] / "www" / "media"
    static_paths = [
        StaticPathConfig(_URL_PATH, str(js_path), cache_headers=False),
    ]
    if media_path.is_dir():
        static_paths.append(
            StaticPathConfig(f"/local/{DOMAIN}/media", str(media_path), cache_headers=True)
        )
    await hass.http.async_register_static_paths(static_paths)
    frontend.add_extra_js_url(hass, _MODULE_URL)
    domain_data[_DATA_KEY] = True


def async_unload_frontend_loader(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.pop(_DATA_KEY, False):
        return
    frontend.remove_extra_js_url(hass, _MODULE_URL)
