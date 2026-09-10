"""
subscriber.py

SecureEV MQTT subscriber.

Receives telemetry, control, and later security-related messages from the
virtual vehicle network.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from network.mqtt_config import (
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_KEEPALIVE,
)


MessageHandler = Callable[[str, dict[str, Any]], None]


class MQTTSubscriber:
    """Reusable MQTT subscriber with JSON parsing and safe callbacks."""

    def __init__(
        self,
        client_id: str = "secureev-subscriber",
        message_handler: Optional[MessageHandler] = None,
        verbose: bool = True,
    ) -> None:
        self.client_id = client_id
        self.message_handler = message_handler
        self.verbose = verbose

        self.connected = False
        self._connected_event = threading.Event()
        self.received_event = threading.Event()

        self.last_topic: Optional[str] = None
        self.last_message: Optional[dict[str, Any]] = None

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)

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
            self._log(
                f"[MQTT Subscriber] Connected to "
                f"{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}"
            )
        else:
            print(
                f"[MQTT Subscriber] Connection failed: {reason_code}"
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
        self._log(
            f"[MQTT Subscriber] Disconnected. Reason={reason_code}"
        )

    def _on_message(self, client, userdata, message) -> None:
        topic = message.topic
        raw_payload = message.payload.decode("utf-8", errors="replace")

        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            print(f"[MQTT RECEIVED] {topic} -> INVALID JSON")
            return

        if not isinstance(payload, dict):
            print(
                f"[MQTT RECEIVED] {topic} -> JSON payload is not an object"
            )
            return

        self.last_topic = topic
        self.last_message = payload
        self.received_event.set()

        self._log(f"[MQTT RECEIVED] {topic} -> {payload}")

        if self.message_handler is not None:
            try:
                self.message_handler(topic, payload)
            except Exception as exc:
                print(f"[MQTT Subscriber] Handler error: {exc}")

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to the broker and wait for CONNACK."""

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
            print(f"[MQTT Subscriber] Connection error: {exc}")
            return False

        if not self._connected_event.wait(timeout):
            print("[MQTT Subscriber] Connection timeout.")
            return False

        return self.connected

    def subscribe(self, topic: str, qos: int = 1) -> bool:
        """Subscribe to a topic."""

        if not self.connected:
            print("[MQTT Subscriber] Not connected.")
            return False

        if not topic:
            raise ValueError("topic cannot be empty.")

        try:
            result, _mid = self.client.subscribe(topic, qos=qos)

            if result != mqtt.MQTT_ERR_SUCCESS:
                print(
                    f"[MQTT Subscriber] Subscribe failed: rc={result}"
                )
                return False

            self._log(f"[MQTT Subscriber] Subscribed: {topic}")
            return True

        except Exception as exc:
            print(f"[MQTT Subscriber] Subscribe error: {exc}")
            return False

    def disconnect(self) -> None:
        """Disconnect cleanly."""

        try:
            if self.client.is_connected():
                self.client.disconnect()
        except Exception:
            pass
        finally:
            try:
                self.client.loop_stop()
            except Exception:
                pass
            self.connected = False
            self._connected_event.clear()
