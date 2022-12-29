""" Description: Main entry point for the miflora-mqtt-daemon
"""
from typing import Any
import asyncio
import json
import platform
from datetime import date, datetime
from collections import OrderedDict
from bleak import BleakScanner, BLEDevice, AdvertisementData
from . import print_line, reporting_mode, sd_notifier, flores
from .mqtt import start_mqtt, found_mqtt, send_mqtt
from .parser import XiaomiBluetoothDeviceData
from home_assistant_bluetooth.models import BluetoothServiceInfoBleak as bti

devices = {}

if platform.system() == "Linux":
    from bleak.assigned_numbers import AdvertisementDataType
    from bleak.backends.bluezdbus.scanner import BlueZScannerArgs
    from bleak.backends.bluezdbus.advertisement_monitor import OrPattern
    # or_patterns is a workaround for the fact that passive scanning
    # needs at least one matcher to be set. The below matcher
    # will match all devices.
    PASSIVE_SCANNER_ARGS = BlueZScannerArgs(
        or_patterns=[
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x06"),
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x1a"),
        ]
    )


async def print_device(device: BLEDevice, data: AdvertisementData):
    """ Print device information """

    if device.name is not None and len(device.name) > 0:  # == "Flower care":
        flora = devices.get(device.address)
        if flora is None:
            devices[device.address] = device
            print_line(f"*** Found device: {device}", warning=True)
            if not flores.get(device.address) is None:
                flora = flores[device.address]
                found_mqtt(f'{flora["name_pretty"]}@{flora["location_pretty"]}')
                print_line(f"*** Adding device: {device}", warning=True)
                flora.poller = 'bleak'
                flora.detected = date.today()
                flora.last_seen = date.today()
                flora.data = XiaomiBluetoothDeviceData()
                print_line(f"*** Added device: {device}", warning=True)

        if not flores.get(device.address) is None:
            flora = flores[device.address]
            serviceInfo=bti.from_device_and_advertisement_data(device, data, 'bleak',
                                                   datetime.now().timestamp(),
                                                   True)
            print_line(f"uuids: {data.service_uuids}")
            flora.data.update(serviceInfo)
            flora.last_seen = date.today()

            print_line(f"Data retrieved for {device.address}: {json.dumps(flora)} ")
            vals={}
            for key, value in flora.data._sensor_values.items():
                vals[key.key] = value.native_value
            print_line(json.dumps(vals))

            send_mqtt(json.dumps(flora))


async def main():
    """ Main entry point of the app """

    stop_event = asyncio.Event()

    if reporting_mode in ['mqtt-json', 'mqtt-smarthome', 'homeassistant-mqtt',
                          'thingsboard-json', 'wirenboard-mqtt']:
        start_mqtt()

    sd_notifier.notify('READY=1')

    scanner_kwargs: dict[str, Any] = {"detection_callback": print_device}
    #  scanner_kwargs["scanning_mode"] = "passive"
    if platform.system() == "Linux":
        if scanner_kwargs["scanning_mode"] == "passive":
            scanner_kwargs["bluez"] = PASSIVE_SCANNER_ARGS

    async with BleakScanner(**scanner_kwargs) as scanner:        
        print_line("Starting BLE passive scanner...")
        await scanner.start()
        print_line("BLE passive scanner started.")
        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            print_line("Stopping scanner...")
            await scanner.stop()
            print_line("Scanner stopped...")


if __name__ == "__main__":
    asyncio.run(main())
