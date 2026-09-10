"""
test_connection.py

Quick sanity check: is CarlaUE4.exe running and reachable?
Run this BEFORE anything else, every time you start a new work session.
"""

import carla


def main():
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)

    world = client.get_world()
    print(f"Connected successfully. Current map: {world.get_map().name}")


if __name__ == "__main__":
    main()
