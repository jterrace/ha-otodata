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

# --- CONFIGURATION (Environment Variables) ---
MQTT_BROKER: str = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT: int = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER: Optional[str] = os.getenv("MQTT_USER")
MQTT_PASS: Optional[str] = os.getenv("MQTT_PASS")

# The central availability topic for the bridge itself
BRIDGE_TOPIC: str = os.getenv("BRIDGE_TOPIC", "otodata/bridge/status")
HA_PREFIX: str = "homeassistant"

# --- CONSTANTS ---
OTODATA_MFG_ID: int = 945  # 0x03B1
OTODATA_PREFIX: bytes = b"OTO"

# --- GLOBAL STATE ---
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
        "model": "TM6030",
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


def parse_serial(mfg_data: bytes) -> Optional[str]:
    """Extracts the 4-byte serial (Little Endian) from Otodata manufacturer bytes."""
    try:
        if mfg_data.startswith(OTODATA_PREFIX):
            # Serial starts at byte 7, 4 bytes long
            serial_int = int.from_bytes(mfg_data[7:11], byteorder="little")
            return str(serial_int)
    except (IndexError, ValueError):
        pass
    return None


def on_connect(
    client: paho.mqtt.client.Client,
    userdata: Any,
    flags: Dict[str, Any],
    rc: paho.mqtt.reasoncodes.ReasonCode,
    props: paho.mqtt.properties.Properties | None,
) -> None:
    """Publish online status immediately upon connection."""
    if rc == 0:
        logging.info(f"Connected to MQTT Broker ({MQTT_BROKER})")
        client.publish(BRIDGE_TOPIC, "online", retain=True)
    else:
        logging.error(f"MQTT Connection failed with code {rc}")


def detection_callback(
    device: BLEDevice, adv: AdvertisementData, client: paho.mqtt.client.Client
) -> None:
    """Main BLE processing loop."""
    # 1. Look for Otodata Manufacturer Data to link MAC to Serial
    mfg_bytes: Optional[bytes] = adv.manufacturer_data.get(OTODATA_MFG_ID)
    if mfg_bytes:
        serial = parse_serial(mfg_bytes)
        if serial:
            if device.address not in known_tanks:
                known_tanks[device.address] = serial
                publish_ha_discovery(client, serial)

    # 2. If we know this MAC is a tank, look for the 'Friendly Name' level data
    if device.address in known_tanks:
        serial = known_tanks[device.address]
        name = adv.local_name or ""
        match = re.search(r"level:\s*([\d.]+)", name)

        if match:
            level = float(match.group(1))
            payload = {"level": level, "rssi": adv.rssi, "mac": device.address}
            client.publish(f"otodata/{serial}/state", json.dumps(payload), retain=True)
            logging.info(f"📊 [{serial}] {level}%")


async def main() -> None:
    logging.info(f"📡 Initializing MQTT connection to {MQTT_BROKER}:{MQTT_PORT}...")
    client = paho.mqtt.client.Client(
        callback_api_version=paho.mqtt.enums.CallbackAPIVersion.VERSION2,
        client_id="otodata"
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
