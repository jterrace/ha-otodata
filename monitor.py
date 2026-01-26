import asyncio
import re
import json
import logging
import os
from typing import Optional, Set, Dict, Any

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import paho.mqtt
import paho.mqtt.client

MQTT_BROKER: str = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER: Optional[str] = os.getenv("MQTT_USER")
MQTT_PASS: Optional[str] = os.getenv("MQTT_PASS")
# The central availability topic for the bridge itself
BRIDGE_TOPIC: str = os.getenv("BRIDGE_TOPIC", "otodata/bridge/status")
# Home assistant prefix
HA_PREFIX: str = os.getenv("HA_PREFIX", "homeassistant")

# BLE manufacturer ID for Otodata
OTODATA_MFG_ID: int = 945  # 0x03B1
OTODATA_MODEL_NUMBER: str = "TM6030"

# Maps MAC Address -> Serial Number
known_tanks: Dict[str, str] = {}
# Tracks which serials have been "discovered" by HA
configured_serials: Set[str] = set()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def publish_ha_discovery(client: paho.mqtt.client.Client, serial: str) -> None:
    """
    Publishes discovery payloads for a specific tank serial.
    Both entities point to the global BRIDGE_TOPIC for availability.
    """
    if serial in configured_serials:
        return

    device_info: Dict[str, Any] = {
        "identifiers": [f"otodata_{serial}"],
        "name": f"Propane Tank {serial}",
        "manufacturer": "Otodata",
        "model": OTODATA_MODEL_NUMBER,
    }

    # 1. Level Sensor
    config_level = {
        "name": "Propane Level",
        "unique_id": f"otodata_{serial}_level",
        "state_topic": f"otodata/{serial}/state",
        "availability_topic": BRIDGE_TOPIC,
        "unit_of_measurement": "%",
        "value_template": "{{ value_json.level }}",
        "device_class": "gas",
        "icon": "mdi:propane-tank",
        "device": device_info,
    }
    client.publish(
        f"{HA_PREFIX}/sensor/otodata_{serial}/level/config",
        json.dumps(config_level),
        retain=True,
    )

    # 2. RSSI Diagnostic
    config_rssi = {
        "name": "Signal Strength",
        "unique_id": f"otodata_{serial}_rssi",
        "state_topic": f"otodata/{serial}/state",
        "availability_topic": BRIDGE_TOPIC,
        "unit_of_measurement": "dBm",
        "value_template": "{{ value_json.rssi }}",
        "device_class": "signal_strength",
        "entity_category": "diagnostic",
        "device": device_info,
    }
    client.publish(
        f"{HA_PREFIX}/sensor/otodata_{serial}/rssi/config",
        json.dumps(config_rssi),
        retain=True,
    )

    logging.info(
        f"🆕 Discovered Tank: {serial}. Pointed to availability: {BRIDGE_TOPIC}"
    )
    configured_serials.add(serial)


def on_connect(
    client: paho.mqtt.client.Client,
    userdata: Any,
    flags: Dict[str, Any],
    rc: paho.mqtt.reasoncodes.ReasonCode,
    props: paho.mqtt.properties.Properties | None,
) -> None:
    """Publish online status immediately upon connection."""
    if rc != 0:
        logging.error(f"MQTT Connection failed with code {rc}")
        return

    logging.info(f"Connected to MQTT Broker ({MQTT_BROKER})")
    client.publish(BRIDGE_TOPIC, "online", retain=True)


def detection_callback(
    device: BLEDevice, adv: AdvertisementData, client: paho.mqtt.client.Client
) -> None:
    """Main BLE processing loop."""
    # AdvertisementData(local_name='TM6030 20479133',
    #                   manufacturer_data={945: b'OTOSTAT\x01s\x00s\x00\x8a\xbc\x04\x00\x07\xb7\x00\x00\x00\x00\x00\x00'},
    #                   rssi=-91)
    if OTODATA_MFG_ID in adv.manufacturer_data and adv.local_name.startswith(
        OTODATA_MODEL_NUMBER
    ):
        serial = adv.local_name[len(OTODATA_MODEL_NUMBER) :].strip()
        known_tanks[device.address] = serial
        publish_ha_discovery(client, serial)

    # AdvertisementData(local_name='level: 80.0 % vertical',
    #                   manufacturer_data={945: b'OTOTELE\x02\x00\x12\x1d\x00\x05p6\x06\x18\x00\x00\xff\x00\x00\x00\x00'},
    #                   rssi=-91)
    if device.address in known_tanks and adv.local_name.startswith("level:"):
        serial = known_tanks[device.address]
        name = adv.local_name or ""
        match = re.search(r"level:\s*([\d.]+)", name)
        if not match:
            logging.error(f"❌ [{serial}] Failed to parse level from '{name}'")
            return
        level = float(match.group(1))
        payload = {"level": level, "rssi": adv.rssi, "mac": device.address}
        client.publish(f"otodata/{serial}/state", json.dumps(payload), retain=True)
        logging.info(f"📊 [{serial}] {level}%")


async def main() -> None:
    logging.info(f"📡 Initializing MQTT connection to {MQTT_BROKER}:{MQTT_PORT}...")
    client = paho.mqtt.client.Client(
        callback_api_version=paho.mqtt.enums.CallbackAPIVersion.VERSION2,
        client_id="otodata",
    )
    client.will_set(BRIDGE_TOPIC, payload="offline", qos=1, retain=True)
    client.on_connect = on_connect
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_start()
    client.username_pw_set(MQTT_USER, MQTT_PASS)

    logging.info("📡 MQTT connection initialized.")

    async with BleakScanner(
        detection_callback=lambda d, a: detection_callback(d, a, client)
    ):
        logging.info("📡 Bleak started listening for Otodata broadcasts.")
        while True:
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bridge stopped by user.")
