import carla
import random
import time


def main():
    print("Connecting to CARLA...")

    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)

    world = client.get_world()

    print(f"Connected to: {world.get_map().name}")

    # Get blueprint library
    blueprint_library = world.get_blueprint_library()

    # Find Tesla Model 3
    blueprints = blueprint_library.filter("vehicle.tesla.model3")

    if not blueprints:
        print("ERROR: Tesla Model 3 blueprint not found.")
        return

    vehicle_bp = blueprints[0]
    vehicle_bp.set_attribute("role_name", "secureev")

    # Find a free spawn point
    spawn_points = world.get_map().get_spawn_points()
    random.shuffle(spawn_points)

    vehicle = None

    for spawn_point in spawn_points:
        vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)

        if vehicle is not None:
            break

    if vehicle is None:
        print("ERROR: Could not spawn vehicle.")
        return

    print("✓ SecureEV Tesla Model 3 spawned!")
    print(f"Vehicle ID: {vehicle.id}")

    try:
        # Enable CARLA autopilot
        vehicle.set_autopilot(True)

        print("✓ Autopilot enabled")
        print("Vehicle is driving for 20 seconds...\n")

        for second in range(20):
            velocity = vehicle.get_velocity()
            location = vehicle.get_location()

            # Convert velocity from m/s to km/h
            speed = 3.6 * (
                velocity.x ** 2 +
                velocity.y ** 2 +
                velocity.z ** 2
            ) ** 0.5

            print(
                f"[{second + 1:02d}s] "
                f"Speed: {speed:6.2f} km/h | "
                f"Position: "
                f"({location.x:.1f}, {location.y:.1f}, {location.z:.1f})"
            )

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping simulation...")

    finally:
        # Disable autopilot and remove vehicle
        if vehicle is not None:
            vehicle.set_autopilot(False)
            vehicle.destroy()
            print("\n✓ SecureEV vehicle destroyed.")

        print("Phase 1C complete!")


if __name__ == "__main__":
    main()