"""Test helpers shared across the GeoDrops tests."""

from unittest.mock import AsyncMock, patch


class FakeGeoDropsClient:
    """Stands in for aiogeodrops.GeoDropsClient (patched in by conftest.py).

    By default every call succeeds with no data. Tests change a method with
    patch_client(), which patches the class, so it applies to clients that
    already exist (e.g. the coordinator's) as well as ones created later.
    """

    created = []  # (project_id, credentials) of every client made
    init_error = None  # raised by the constructor when set

    def __init__(self, session, project_id, credentials):
        if self.init_error is not None:
            raise self.init_error
        type(self).created.append((project_id, credentials))
        self.project_id = project_id
        self.missing_columns = frozenset()

    async def validate_access(self):
        return None

    async def lookup_serial(self, serial, lookback_hours):
        return None

    async def fetch_latest(self, device_ids, lookback_hours):
        return {}

    async def fetch_battery_history(self, device_ids, days):
        return {}


def patch_client(method, **kwargs):
    """Replace one client method with an AsyncMock(**kwargs), e.g. side_effect=error."""
    return patch.object(FakeGeoDropsClient, method, AsyncMock(**kwargs))


def patch_client_init(error):
    """Make creating a client raise `error` (an unusable key)."""
    return patch.object(FakeGeoDropsClient, "init_error", error)
