"""Check that the local CARLA RPC API is actually responsive."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        import carla

        client = carla.Client("127.0.0.1", 2000)
        client.set_timeout(5.0)
        version = client.get_server_version()
        world = client.get_world()
        map_name = world.get_map().name
    except Exception as exc:
        print(f"CARLA_API_ERROR: {exc}")
        return 1

    print(f"CARLA_SERVER_VERSION: {version}")
    print(f"CARLA_MAP: {map_name}")
    return 0 if str(version).strip() == "0.9.16" else 2


if __name__ == "__main__":
    raise SystemExit(main())
