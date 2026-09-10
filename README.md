SecureEV

Attack Resistant Cybersecurity Measures for Next-Gen Connected EVs

SecureEV is a real-time digital-twin-based cybersecurity testbed for next-generation connected electric vehicles. The project simulates a connected EV in CARLA, models vehicle ECUs and their state, exposes an MQTT-based virtual in-vehicle communication network, launches controlled cyberattacks, validates telemetry against trusted ground truth, and applies attack-resistant responses such as blocking, ECU isolation, data trust revocation, and emergency braking.

The project is designed as a cybersecurity system first. CARLA is the physical/3D simulation and trusted ground-truth layer, while MQTT provides the connected-vehicle communication attack surface.

Core Security Goal

SecureEV follows this security loop:

Attack
  ↓
Detection
  ↓
Ground-Truth Verification
  ↓
Mitigation / Blocking
  ↓
Safe State
  ↓
Recovery
  ↓
Security Evaluation

The long-term objective is to demonstrate that a connected EV can continue operating safely even when its communication network or telemetry is being attacked.

System Architecture

                    NEXT-GEN CONNECTED EV
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
        CARLA            Digital Twin       MQTT Network
  physical/3D ground       ECUs/state       virtual EV network
      truth layer              │                  │
          │                     └────────┬─────────┘
          ▼                              ▼
      CarlaBridge                   Red Team / Blue Team
   ONLY module importing              attacks / defense
       CARLA                               │
          │                                ▼
          └────── VehicleState      Ground Truth Validator
                                         │
                                         ▼
                                   Response Engine
                                         │
                                         ▼
                                  Attack-resistant
                                  response/recovery
                                         │
                                         ▼
                                  Dashboard/backend

Important architecture rule

simulation/carla_bridge.py is the only project module that directly imports or communicates with CARLA.

ECUs must not import CARLA directly. They operate through CarlaBridge and the shared digital-twin vehicle state.

Technology Stack

Simulation

CARLA 0.9.15

Unreal Engine based vehicle simulation

Tesla Model 3 test vehicle

Town10HD environment

Programming

Python 3.10 for the CARLA development environment

Pygame for the development/testing cockpit

Vehicle / Digital Twin

VehicleState

VCU

BMS

BCM

MCU

TCU

ACU

Charging Controller

Camera Module

OTA Manager

DigitalTwinManager

Networking

MQTT

Mosquitto broker

Paho MQTT 2.x

Planned application layer

FastAPI

WebSocket

PostgreSQL / SQLAlchemy

React

Three.js / React Three Fiber

Current Project Structure

SecureEV/
├── backend/
│   └── main.py
│
├── blue_team/
│   ├── detection_engine.py
│   ├── ground_truth_validator.py
│   ├── integrity_checker.py
│   ├── response_engine.py
│   ├── runtime_response.py
│   └── security_gateway.py
│
├── database/
│   └── models.py
│
├── digital_twin/
│   ├── vehicle_state.py
│   ├── base_ecu.py
│   ├── vcu.py
│   ├── bms.py
│   ├── bcm.py
│   ├── mcu.py
│   ├── tcu.py
│   ├── acu.py
│   ├── camera_module.py
│   ├── charging_controller.py
│   ├── ota_manager.py
│   ├── digital_twin_manager.py
│   └── tests/
│
├── network/
│   ├── mqtt_config.py
│   ├── publisher.py
│   ├── subscriber.py
│   ├── control_schema.py
│   ├── control_bridge.py
│   ├── ecu_telemetry_bridge.py
│   ├── test_mqtt_control_path.py
│   ├── test_phase5_security_gateway.py
│   ├── test_phase6_control_injection.py
│   ├── test_phase6b_data_spoofing.py
│   ├── test_phase7_ground_truth_validation.py
│   └── test_phase8a_response_engine.py
│
├── red_team/
│   ├── attack_manager.py
│   ├── control_injection.py
│   ├── data_integrity_attacks.py
│   ├── data_spoofing.py
│   └── firmware_attacks.py
│
├── simulation/
│   ├── carla_bridge.py
│   ├── manual_drive.py
│   ├── drive_vehicle.py
│   ├── spawn_vehicle.py
│   └── test_connection.py
│
├── frontend/
├── logs/
├── reports/
├── requirements.txt
└── README.md

The project structure will grow as the FastAPI, database, React dashboard, recovery, and final evaluation layers are integrated.

Environment Setup

1. CARLA

The current development target is CARLA 0.9.15.

For the stable local configuration used during development:

.\CarlaUE4.exe -quality-level=Low -nosound -windowed -ResX=1024 -ResY=576

The project has been tested with a lower resolution and low quality because the development laptop previously experienced Unreal/D3D device-loss issues at heavier settings.

2. Python

Use Python 3.10 for the CARLA environment.

Example virtual environment:

py -3.10 -m venv venv_carla915
.\venv_carla915\Scripts\Activate.ps1

Verify:

python --version

3. Install dependencies

pip install -r requirements.txt

Current core Python dependencies include:

carla==0.9.15
pygame>=2.5.0,<2.7.0
paho-mqtt>=2.1.0,<3.0

4. Mosquitto

SecureEV uses a local Mosquitto broker:

Host: localhost
Port: 1883

Start it with:

mosquitto

A successful basic MQTT test should show communication such as:

secureev/test
SECUREEV MQTT TEST

Vehicle State

The digital twin uses a shared VehicleState object containing core EV state, including:

speed_kmh
acceleration
doors_locked
doors_open
battery_soc
battery_temp
motor_temp
motor_rpm
reported_gps
autonomous_mode
planned_steer
planned_throttle
planned_brake
charging_state
charge_port_locked
vehicle_disabled_flag
camera_feed_source
firmware_version
last_updated

The state is updated by the digital-twin ECUs and synchronized with the simulation through CarlaBridge.

ECU Responsibilities

VCU — Vehicle Control Unit

Responsible for:

speed and acceleration ownership

throttle, brake, and steering commands

emergency braking

live vehicle telemetry

BMS — Battery Management System

Responsible for:

state of charge

battery temperature

energy statistics

charging-related state integration

BCM — Body Control Module

Responsible for:

doors

locking state

body-related controls

MCU — Motor Control Unit

Responsible for:

motor RPM

motor temperature

TCU — Telematics Control Unit

Responsible for:

GPS/location information

network-facing telematics data

ACU — Autonomous Control Unit

Responsible for:

manual/autonomous mode

target speed

planned throttle, brake, and steering

Charging Controller

Responsible for:

charger state

charging start/stop behavior

interaction with battery state

Camera Module

Responsible for:

simulated camera state/feed metadata

Raw camera video is intentionally not sent over MQTT. Camera transport is planned as a separate data path for the final dashboard.

OTA Manager

Responsible for:

firmware update state

firmware version tracking

simulated update/signature validation

The current OTA validation is a controlled simulated signature gate, not a complete production-grade cryptographic update framework.

MQTT Communication

MQTT represents the virtual connected-vehicle network and attack surface.

Broker

localhost:1883

Topics

secureev/vcu/telemetry
secureev/vcu/control

secureev/bms/telemetry
secureev/bms/control

secureev/bcm/telemetry
secureev/bcm/control

secureev/mcu/telemetry
secureev/mcu/control

secureev/tcu/telemetry
secureev/tcu/control

secureev/acu/telemetry
secureev/acu/control

secureev/charging/telemetry
secureev/charging/control

secureev/camera/telemetry
secureev/camera/control

secureev/ota/telemetry
secureev/ota/control

secureev/security/alerts
secureev/test/python

Standard message envelope

{
  "protocol_version": 1,
  "message_id": "uuid",
  "vehicle_id": "SEV-001",
  "ecu": "VCU",
  "message_type": "telemetry",
  "timestamp": 1789036664.66,
  "sequence": 1,
  "data": {}
}

ECU telemetry uses independent sequence counters.

Security Gateway

Before MQTT control messages reach the VCU, they pass through the Phase 5 security gateway.

MQTT
 ↓
Security Gateway
 ↓
Identity Check
 ↓
Topic Check
 ↓
Vehicle ID Check
 ↓
Timestamp / Freshness Check
 ↓
Sequence / Replay Check
 ↓
Payload / Range Check
 ↓
Command Authorization
 ↓
ALLOW / BLOCK
 ↓
VCU

Current deterministic checks include:

protocol version

vehicle ID

ECU identity

expected MQTT topic

message type

message ID

timestamp freshness

future timestamp rejection

replay detection

sequence monotonicity

allowed commands

throttle/brake/steering ranges

Current security limitation

The current local MQTT testbed does not yet provide cryptographic publisher authentication. In particular, a message can still syntactically claim vehicle_id = SEV-001 unless stronger identity/authentication is added.

This is a known future hardening item and should not be presented as full production authentication.

Red Team

The Red Team represents a controlled attacker operating against the simulated connected-vehicle network.

All attacks are designed for the isolated project/test environment.

Implemented attack classes

Control injection

forged vehicle identity

out-of-range throttle/control values

replay of accepted control messages

unauthorized command injection

Telemetry spoofing

VCU speed spoofing

BMS battery SOC spoofing

TCU GPS spoofing

Planned / extending attack classes

communication disruption / ECU availability attacks

OTA/firmware manipulation

malformed messages

additional integrity attacks

Blue Team

The Blue Team represents the defensive security stack.

Current capabilities include:

Detection

Receives and inspects security-relevant messages.

Ground Truth Validation

Compares network-reported telemetry against trusted vehicle reality.

Examples:

CARLA speed = 0 km/h
MQTT speed  = 180 km/h
→ speed integrity violation

CARLA position != TCU reported GPS
→ GPS spoofing detected

For battery state, SecureEV currently uses a trusted digital-twin SOC reference because CARLA does not provide battery SOC as physical simulation ground truth.

Response Engine

Current response policy is severity-based:

INFO
 → MONITOR

HIGH
 → ISOLATE ECU
 → MARK DATA UNTRUSTED

CRITICAL
 → ISOLATE ECU
 → MARK DATA UNTRUSTED
 → EMERGENCY BRAKE

Runtime Response

Phase 8B connects the response engine to the real VCU and CARLA vehicle.

A critical security finding can now cause:

Attack
 ↓
Detection
 ↓
Ground-truth verification
 ↓
Response engine
 ↓
VCU emergency brake
 ↓
CARLA vehicle reaches 0 km/h

Pygame Development Cockpit

Pygame is a development and validation cockpit, not the final product dashboard.

Current manual-driving controls:

W / Up Arrow       Accelerate
S / Down Arrow     Brake
A / Left Arrow     Steer left
D / Right Arrow    Steer right
Space              Emergency brake
R                  Reset
C                  Camera cycle
ESC                Exit

Phase 3 subsystem controls:

M   Manual / Autonomous
G   Connect / Disconnect charger
T   Start charging
X   Stop charging
U   Simulated valid OTA update

The current Pygame cockpit will be extended after recovery testing into the first integrated live SecureEV cybersecurity demonstration.

Testing Roadmap and Verified Status

Phase 0 — Environment

Status: PASSED

CARLA, Python, Pygame, MQTT, and the local development environment were established.

Phase 1 — CARLA Foundation

Status: PASSED

CARLA connectivity, vehicle spawning, driving, and bridge communication were established.

Phase 2 — Digital Twin + Core ECUs

Status: PASSED

VehicleState and the main ECU modules were implemented and integrated.

Phase 2.5 — Interactive Manual Driving

Status: PASSED

The Tesla Model 3 can be manually driven using the Pygame development cockpit.

Phase 3 — Vehicle Subsystems

Status: PASSED

Charging, camera, ACU, OTA, and related vehicle subsystem behaviors were integrated and tested.

Phase 4A — MQTT Infrastructure

Status: PASSED

Mosquitto and the SecureEV MQTT topic architecture were established.

Phase 4B — Python MQTT Messaging

Status: PASSED

Python publisher/subscriber communication and message schema validation were verified.

Phase 4C — Live VCU → MQTT

Status: PASSED

Live VCU telemetry was published from the moving simulated Tesla.

Phase 4D — Multi-ECU MQTT

Status: PASSED

VCU, BMS, BCM, MCU, and TCU telemetry were verified through MQTT.

Verified test total:

Total MQTT messages: 365
VCU: 73
BMS: 73
BCM: 73
MCU: 73
TCU: 73

Phase 4E — Extended ECU MQTT

Status: PASSED

ACU, charging controller, OTA manager, and the additional telemetry paths were integrated.

Verified test total:

Total MQTT messages: 432
VCU: 54
BMS: 54
BCM: 54
MCU: 54
TCU: 54
ACU: 54
CHG: 54
OTA: 54

OTA behavior included acceptance of a valid simulated update and rejection of a tampered update.

Phase 4F — MQTT Command Path

Status: PASSED

MQTT commands can control the VCU through the protected command bridge.

Verified:

throttle command

braking command

emergency brake

command queue processing

accepted/rejected accounting

Phase 5 — Security Gateway

Status: PASSED

Verified defenses:

replay detection

sequence validation

freshness validation

vehicle identity validation

command authorization

topic validation

Latest verified result:

Gateway checked : 9
Gateway allowed : 3
Gateway blocked : 6
Bridge accepted : 3
Bridge rejected : 6

Phase 6A — Red Team Control Injection

Status: PASSED

Four controlled control-injection scenarios were blocked:

unauthorized_acceleration
out_of_range_control
replay_control
unauthorized_command

Verified:

Attack scenarios launched : 4
Attack scenarios failed   : 0
Gateway blocked           : 4
No physical control change: PASSED
Sequence preserved        : PASSED
Legitimate command after attacks: PASSED

Phase 6B — Red Team Telemetry Spoofing

Status: PASSED

Three false-data attacks were successfully injected into the MQTT network:

VCU speed = 180 km/h
BMS SOC   = 99%
TCU GPS   = fake coordinates

Verified:

Telemetry attacks launched : 3
Spoofed messages delivered : 3/3
MQTT false-data injection  : PASSED
CARLA physical state unchanged: PASSED

Phase 7 — Ground Truth Validation

Status: PASSED

Legitimate telemetry was accepted as consistent and all three spoofed telemetry scenarios were independently detected against trusted references.

Verified:

Ground-truth checks performed : 6
Anomalies detected             : 3
Consistent samples             : 3

Detected severities:

speed_spoofing       → HIGH
battery_soc_spoofing → HIGH
gps_spoofing          → CRITICAL

Phase 8A — Attack-Resistant Response Policy

Status: PASSED

Verified severity-based actions:

INFO     → MONITOR
HIGH     → ISOLATE + MARK UNTRUSTED
CRITICAL → ISOLATE + MARK UNTRUSTED + EMERGENCY BRAKE

Phase 8B — Runtime Response Integration

Status: PASSED

The response engine was connected to the real VCU/CARLA runtime.

Verified:

HIGH finding:
  isolate + untrust
  no unnecessary emergency brake

CRITICAL finding:
  isolate + untrust
  emergency brake
  CARLA vehicle reaches 0 km/h

Runtime accounting:

Handled findings : 2
Detected findings: 2
Emergency brakes : 1

Phase 9 — Recovery

Status: NEXT

Planned recovery behavior includes:

ATTACKED
  ↓
ISOLATED
  ↓
RECOVERY_PENDING
  ↓
TRUST_RESTORED
  ↓
RECOVERED

The system will verify that affected ECUs and trusted telemetry can return to safe operation after an attack has been contained.

Phase 10 — Security Evaluation

Status: PLANNED

Planned metrics include:

attack detection rate

false positive rate

detection time

response time

mitigation/blocking rate

recovery time

ECU availability

vehicle availability

residual risk

Phase 11 — FastAPI Backend

Status: PLANNED

The backend will expose live SecureEV state and security events to the dashboard.

Phase 12 — Database

Status: PLANNED

Security alerts, attack history, telemetry records, recovery events, and evaluation metrics will be stored for analysis.

Phase 13 — React Dashboard

Status: PLANNED

The dashboard will provide:

live vehicle/camera view

speed and battery status

motor data

GPS status

ECU health

security threat level

active attack

detection status

mitigation state

attack history

logs

risk analytics

Phase 14 — Final Security Evaluation

Status: PLANNED

The complete attack → detect → verify → mitigate → recover loop will be measured and documented.

Phase 15 — Final Demonstration

Status: PLANNED

The final demonstration will combine CARLA, SecureEV core services, MQTT, Red Team attacks, Blue Team defense, Pygame development cockpit, and the final dashboard.

Integrated Demo Plan

The final live demonstration is intended to operate as follows:

CARLA
  ↓
SecureEV Digital Twin
  ↓
MQTT Vehicle Network
  ↓
Red Team launches attack
  ↓
Security Gateway
  ↓
Ground Truth Validator
  ↓
Response Engine
  ↓
Safe State / ECU Isolation
  ↓
Recovery
  ↓
Dashboard + Logs + Metrics

Example demonstration scenario:

1. Drive Tesla in CARLA/Pygame.
2. Establish normal telemetry.
3. Launch a controlled control or telemetry attack.
4. Show the malicious network behavior.
5. Show Security Gateway blocking where applicable.
6. Show CARLA ground-truth mismatch for spoofed data.
7. Show security severity.
8. Trigger the appropriate response.
9. Show vehicle entering a safe state.
10. Recover the affected subsystem.
11. Display the attack, response, and recovery metrics.

Known Technical Notes

Acceleration telemetry

Very sharp calculated acceleration values can occur around hard stops because of sampling and numerical differences. Acceleration should therefore be smoothed or bounded before it is used as a standalone anomaly-detection feature to reduce false positives.

Camera transport

The Pygame/CARLA camera is treated separately from the MQTT telemetry/control network. Raw RGB video should not be pushed through MQTT for the final architecture.

MQTT threading

Paho MQTT callbacks should not call CARLA directly. Validated commands are queued and processed by the main simulation/control loop.

Security scope

SecureEV is a controlled academic cybersecurity testbed. It demonstrates defensive architecture and measurable attack scenarios rather than claiming production automotive certification or complete in-vehicle security compliance.

Development Philosophy

SecureEV follows a checkpoint-based implementation strategy:

Build one layer
   ↓
Test it
   ↓
Validate the result
   ↓
Lock the checkpoint
   ↓
Build the next layer

This prevents later dashboard or analytics work from hiding problems in the underlying vehicle, network, or security logic.

Current Milestone

Phase 0    ✅ Environment
Phase 1    ✅ CARLA Foundation
Phase 2    ✅ Digital Twin + Core ECUs
Phase 2.5  ✅ Interactive Manual Driving
Phase 3    ✅ Vehicle Subsystems
Phase 4A   ✅ MQTT Infrastructure
Phase 4B   ✅ Python MQTT Messaging
Phase 4C   ✅ Live VCU → MQTT
Phase 4D   ✅ Multi-ECU MQTT
Phase 4E   ✅ Extended ECU MQTT
Phase 4F   ✅ MQTT Command Path
Phase 5    ✅ Security Gateway
Phase 6A   ✅ Control Injection
Phase 6B   ✅ Telemetry Spoofing
Phase 7    ✅ Ground Truth Validation
Phase 8A   ✅ Response Policy
Phase 8B   ✅ Runtime Response
Phase 9    🔄 Recovery
Phase 10   ⏳ Security Evaluation
Phase 11   ⏳ FastAPI Backend
Phase 12   ⏳ Database
Phase 13   ⏳ React Dashboard
Phase 14   ⏳ Final Security Evaluation
Phase 15   ⏳ Final Demo

License / Academic Use

This project is developed as an academic cybersecurity and connected-EV simulation project. Attack functionality is intended only for the isolated SecureEV test environment.