SecureEV Phase 4B patch

Copy the files from the network/ directory into:
    SecureEV/network/

Files:
    mqtt_config.py
    message_schema.py
    publisher.py
    subscriber.py
    test_mqtt.py

Requirements:
    Python 3.10
    paho-mqtt 2.1.0
    Mosquitto broker running on localhost:1883

Run from the SecureEV project root:
    python -u -m network.test_mqtt

This test does not require CARLA.
