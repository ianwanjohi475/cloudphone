"""GPS / location spoofing.

Uses Android's mock-location provider. Requires a mock-location app to be set
as the system mock provider (we ship a tiny one in apps/), or root to push
locations directly through `cmd location`/`appops`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adb import Adb


@dataclass
class Location:
    lat: float
    lon: float
    altitude: float = 12.0
    accuracy: float = 5.0


def enable_mock(adb: Adb, package: str = "com.cloudphone.mockgps") -> None:
    """Grant a package permission to provide mock locations."""
    adb.shell(f"appops set {package} android:mock_location allow", check=False)
    adb.shell("settings put secure mock_location 1", check=False)


def set_location(adb: Adb, loc: Location) -> str:
    """Push a fixed location through every provider.

    Prefers the root `cmd location` path (Android 12+); falls back to the
    legacy `geo fix` console and the mock-gps broadcast.
    """
    # Modern, root path: feed both gps + network providers.
    for provider in ("gps", "network", "fused"):
        adb.shell(
            f"su -c 'cmd location providers set-test-provider-location {provider} "
            f"--location {loc.lat},{loc.lon} --accuracy {loc.accuracy} "
            f"--altitude {loc.altitude}'",
            check=False,
        )
    # Broadcast for our mock-gps helper app (non-root path).
    adb.shell(
        "am broadcast -a com.cloudphone.mockgps.SET "
        f"--ef lat {loc.lat} --ef lon {loc.lon} --ef alt {loc.altitude}",
        check=False,
    )
    return f"location set -> {loc.lat},{loc.lon}"


def walk(adb: Adb, points: list[Location], dwell_s: float = 2.0):
    """Iterate a route, setting each waypoint with a dwell — generator of status."""
    import time

    for i, p in enumerate(points):
        yield set_location(adb, p)
        if i < len(points) - 1:
            time.sleep(dwell_s)
