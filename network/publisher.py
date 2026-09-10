"""
publisher.py

SecureEV MQTT publisher.

Used first for Phase 4B testing, then by ECU telemetry publishers.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from network.mqtt_config import (
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_KEEPALIVE,
)


class MQTTPublisher:
    """Small, reusable MQTT publisher for SecureEV."""

    def __init__(self, client_id: str = "secureev-publisher") -> None:
        self.client_id = client_id
        self.connected = False
        self._connected_event = threading.Event()
        self._lock = threading.Lock()

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        if reason_code == 0:
            self.connected = True
            self._connected_event.set()
            print(
                f"[MQTT Publisher] Connected to "
                f"{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}"
            )
        else:
            print(
                f"[MQTT Publisher] Connection failed: {reason_code}"
            )

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        self.connected = False
        self._connected_event.clear()
        print(f"[MQTT Publisher] Disconnected. Reason={reason_code}")

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to the local broker and wait for CONNACK."""

        self._connected_event.clear()

        try:
            self.client.loop_start()
            self.client.connect(
                MQTT_BROKER_HOST,
                MQTT_BROKER_PORT,
                MQTT_KEEPALIVE,
            )
        except Exception as exc:
            self.client.loop_stop()
            print(f"[MQTT Publisher] Connection error: {exc}")
            return False

        if not self._connected_event.wait(timeout):
            print("[MQTT Publisher] Connection timeout.")
            return False

        return self.connected

    def publish(
        self,
        topic: str,
        message: dict[str, Any],
        qos: int = 1,
    ) -> bool:
        """Publish a JSON message."""

        if not self.connected:
            print("[MQTT Publisher] Not connected.")
            return False

        if not topic:
            raise ValueError("topic cannot be empty.")

        payload = json.dumps(message, separators=(",", ":"))

        try:
            with self._lock:
                result = self.client.publish(
                    topic,
                    payload,
                    qos=qos,
                    retain=False,
                )

            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT Publisher] Publish failed: rc={result.rc}")
                return False

            # Wait briefly for QoS 1 acknowledgement when available.
            if qos > 0:
                result.wait_for_publish(timeout=2.0)

            return bool(result.is_published())

        except Exception as exc:
            print(f"[MQTT Publisher] Publish error: {exc}")
            return False

    def disconnect(self) -> None:
        """Stop the network loop and disconnect cleanly."""

        try:
            if self.client.is_connected():
                self.client.disconnect()
        except Exception:
            pass
        finally:
            time.sleep(0.1)
            try:
                self.client.loop_stop()
            except Exception:
                pass
            self.connected = False
            self._connected_event.clear()
