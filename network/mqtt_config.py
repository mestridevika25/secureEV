"""
mqtt_config.py

SecureEV MQTT virtual vehicle network configuration.
"""

MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
MQTT_KEEPALIVE = 60

VEHICLE_ID = "SEV-001"
TOPIC_PREFIX = "secureev"

# Core ECU telemetry/control topics
VCU_TELEMETRY = f"{TOPIC_PREFIX}/vcu/telemetry"
VCU_CONTROL = f"{TOPIC_PREFIX}/vcu/control"

BMS_TELEMETRY = f"{TOPIC_PREFIX}/bms/telemetry"
BMS_CONTROL = f"{TOPIC_PREFIX}/bms/control"

BCM_TELEMETRY = f"{TOPIC_PREFIX}/bcm/telemetry"
BCM_CONTROL = f"{TOPIC_PREFIX}/bcm/control"

MCU_TELEMETRY = f"{TOPIC_PREFIX}/mcu/telemetry"
MCU_CONTROL = f"{TOPIC_PREFIX}/mcu/control"

TCU_TELEMETRY = f"{TOPIC_PREFIX}/tcu/telemetry"
TCU_CONTROL = f"{TOPIC_PREFIX}/tcu/control"

ACU_TELEMETRY = f"{TOPIC_PREFIX}/acu/telemetry"
ACU_CONTROL = f"{TOPIC_PREFIX}/acu/control"

CHARGING_TELEMETRY = f"{TOPIC_PREFIX}/charging/telemetry"
CHARGING_CONTROL = f"{TOPIC_PREFIX}/charging/control"

CAMERA_TELEMETRY = f"{TOPIC_PREFIX}/camera/telemetry"
CAMERA_CONTROL = f"{TOPIC_PREFIX}/camera/control"

OTA_TELEMETRY = f"{TOPIC_PREFIX}/ota/telemetry"
OTA_CONTROL = f"{TOPIC_PREFIX}/ota/control"

SECURITY_ALERTS = f"{TOPIC_PREFIX}/security/alerts"

# Phase 5 control surface. The SecurityGateway still enforces the exact
# protected topic (VCU_CONTROL) after the wildcard subscription receives it.
CONTROL_WILDCARD = f"{TOPIC_PREFIX}/+/control"

# Development-only test topic
TEST_TOPIC = f"{TOPIC_PREFIX}/test/python"
