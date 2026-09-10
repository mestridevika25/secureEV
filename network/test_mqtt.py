"""
test_mqtt.py

SecureEV Phase 4B — Python MQTT integration test.

Tests:
    SecureEV Python Publisher -> Mosquitto -> SecureEV Python Subscriber

No CARLA connection is required for this test.
"""

from __future__ import annotations

import time
import uuid

from network.message_schema import create_message
from network.mqtt_config import TEST_TOPIC
from network.publisher import MQTTPublisher
from network.subscriber import MQTTSubscriber


def main() -> int:
    print()
    print("=" * 50)
    print(" SecureEV - PHASE 4B MQTT TEST")
    print("=" * 50)

    subscriber = MQTTSubscriber(
        client_id=f"secureev-test-sub-{uuid.uuid4().hex[:8]}"
    )

    publisher = MQTTPublisher(
        client_id=f"secureev-test-pub-{uuid.uuid4().hex[:8]}"
    )

    try:
        # ----------------------------------------------------
        # 1. Subscriber
        # ----------------------------------------------------
        print("\n[1] Connecting MQTT subscriber...")

        if not subscriber.connect():
            print("Subscriber connection FAILED.")
            return 1

        if not subscriber.subscribe(TEST_TOPIC):
            print("Subscriber subscription FAILED.")
            return 1

        # Give Mosquitto and the subscription a moment to settle.
        time.sleep(0.5)

        # ----------------------------------------------------
        # 2. Publisher
        # ----------------------------------------------------
        print("\n[2] Connecting MQTT publisher...")

        if not publisher.connect():
            print("Publisher connection FAILED.")
            return 1

        # ----------------------------------------------------
        # 3. Standard SecureEV message
        # ----------------------------------------------------
        message = create_message(
            ecu="VCU",
            message_type="telemetry",
            sequence=1,
            data={
                "speed_kmh": 42.5,
                "acceleration_mps2": 1.2,
                "test": True,
            },
        )

        print("\n[3] Publishing standard SecureEV message...")
        print(f"Topic: {TEST_TOPIC}")
        print(f"Message ID: {message['message_id']}")
        print(f"Sequence: {message['sequence']}")

        published = publisher.publish(TEST_TOPIC, message, qos=1)

        print(f"Publish successful: {published}")

        if not published:
            print("MQTT publish FAILED.")
            return 1

        # ----------------------------------------------------
        # 4. Verify subscriber received it
        # ----------------------------------------------------
        print("\n[4] Waiting for subscriber...")

        received = subscriber.received_event.wait(timeout=5.0)

        if not received:
            print("Subscriber did not receive the message.")
            return 1

        received_message = subscriber.last_message or {}

        checks = [
            subscriber.last_topic == TEST_TOPIC,
            received_message.get("protocol_version") == 1,
            received_message.get("vehicle_id") == "SEV-001",
            received_message.get("ecu") == "VCU",
            received_message.get("message_type") == "telemetry",
            received_message.get("sequence") == 1,
            received_message.get("data", {}).get("speed_kmh") == 42.5,
        ]

        if not all(checks):
            print("Message validation FAILED.")
            print(f"Received: {received_message}")
            return 1

        print("Message validation: PASSED")

        print("\n" + "=" * 50)
        print(" PHASE 4B MQTT TEST PASSED")
        print("=" * 50)
        return 0

    finally:
        print("\n[5] Cleaning up MQTT clients...")
        publisher.disconnect()
        subscriber.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
