from digital_twin.vehicle_state import VehicleState
from digital_twin.bcm import BCM


def print_state(state):

    print(
        f"Doors Locked = {state.doors_locked} | "
        f"Doors Open = {state.doors_open}"
    )


def main():

    vehicle_state = VehicleState()

    bcm = BCM(
        vehicle_state=vehicle_state
    )

    print("\n================================")
    print(" SecureEV - Phase 2 BCM TEST")
    print("================================\n")

    print("[Initial State]")
    print_state(vehicle_state)

    print("\n[1] Unlocking doors...")
    bcm.unlock_doors()
    bcm.tick()
    print_state(vehicle_state)

    print("\n[2] Opening doors...")
    bcm.open_doors()
    bcm.tick()
    print_state(vehicle_state)

    print("\n[3] Closing doors...")
    bcm.close_doors()
    bcm.tick()
    print_state(vehicle_state)

    print("\n[4] Locking doors...")
    bcm.lock_doors()
    bcm.tick()
    print_state(vehicle_state)

    print("\n[5] Testing locked-door protection...")

    try:
        bcm.open_doors()
        print("ERROR: Door opened while locked.")

    except RuntimeError as error:
        print(f"Expected rejection: {error}")

    print("\nBCM telemetry:")
    print(bcm.telemetry())

    print("\n================================")
    print(" BCM TEST PASSED")
    print("================================")


if __name__ == "__main__":
    main()