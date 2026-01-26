# Home Assistant MQTT publisher for the Otodata TM6030 Propane Tank Fuel Monitor via Bluetooth LE

This project provides a Python-based bridge that listens for **Otodata Propane Tank Monitors** (such as the TM6030) via Bluetooth Low Energy (BLE) and publishes the data to **Home Assistant** via MQTT.

It features **Auto-Discovery**, meaning tanks will automatically appear as devices in Home Assistant once detected, and includes a **Last Will and Testament (LWT)** to track the online/offline status of the bridge.

## 🚀 Features

- **Zero-Config Discovery**: Automatically finds and creates sensors for any Otodata tank in range.
- **Precision Tracking**: Parses the "Friendly Name" broadcast for high-accuracy level data.
- **Availability Monitoring**: Marks sensors as "Unavailable" in Home Assistant if the bridge goes down.

## 🛠️ Installation

```bash
$ python3 -m virtualenv venv
$ ./venv/bin/pip install -r requirements.txt
```

You can then manually test it with:

```bash
MQTT_BROKER="192.168.1.50" MQTT_USER="home" MQTT_PASS="pass" ./venv/bin/python monitor.py
```
