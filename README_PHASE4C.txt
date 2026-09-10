SecureEV Phase 4C patch

Copy the files from network/ into:
    SecureEV/network/

Files:
    ecu_telemetry_bridge.py
    test_vcu_mqtt.py

Requirements:
    Python 3.10
    CARLA 0.9.15
    Paho MQTT 2.1.0
    Mosquitto broker on localhost:1883

Run from the SecureEV project root:
    python -u -m network.test_vcu_mqtt

Important:
    This test does NOT attach an RGB camera. It tests the real vehicle-data
    path independently from the rendering workload.
