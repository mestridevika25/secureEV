import carla
import random
import time


def main():
    print("Connecting to CARLA...")

    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)

    world = client.get_world()

    print(f"Connected to map: {world.get_map().name}")

    # Get available vehicle blueprints
    blueprint_library = world.get_blueprint_library()

    # Try to find Tesla Model 3
    vehicle_blueprints = blueprint_library.filter("vehicle.tesla.model3")

    if not vehicle_blueprints:
        print("Tesla Model 3 blueprint not found.")
        print("Available Tesla vehicles:")

        for bp in blueprint_library.filter("vehicle.tesla.*"):
            print(bp.id)

        return

    vehicle_bp = vehicle_blueprints[0]

    # Give the vehicle a role name
    vehicle_bp.set_attribute("role_name", "secureev")

    # Get available spawn points
    spawn_points = world.get_map().get_spawn_points()

    if not spawn_points:
        print("No spawn points found.")
        return

    # Shuffle spawn points to avoid collisions
    random.shuffle(spawn_points)

    vehicle = None

    for spawn_point in spawn_points:
        vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)

        if vehicle is not None:
            break

    if vehicle is None:
        print("Could not spawn the SecureEV vehicle.")
        return

    print("✓ SecureEV vehicle spawned successfully!")
    print(f"Vehicle ID: {vehicle.id}")
    print(f"Vehicle type: {vehicle.type_id}")

    location = vehicle.get_location()

    print(
        f"Initial location: "
        f"x={location.x:.2f}, "
        f"y={location.y:.2f}, "
        f"z={location.z:.2f}"
    )

    print("\nVehicle will remain for 10 seconds...")
    time.sleep(10)

    print("Destroying SecureEV vehicle...")
    vehicle.destroy()

    print("✓ Vehicle destroyed. Test complete!")


if __name__ == "__main__":
    main()