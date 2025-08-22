from __future__ import annotations

from app.services.wb_client import _map_device_to_app_type


def test_device_mapping():
	assert _map_device_to_app_type("pc") == 1
	assert _map_device_to_app_type("android") == 32
	assert _map_device_to_app_type("ios") == 64
	assert _map_device_to_app_type("iphone") == 64
	assert _map_device_to_app_type("tablet") == 64
	assert _map_device_to_app_type("unknown") == 1
