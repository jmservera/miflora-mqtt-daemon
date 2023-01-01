""" Description: Main entry point for the miflora-mqtt-daemon
"""
from collections import OrderedDict
import sys
import time
from typing import Any
import asyncio
import platform
from datetime import date, datetime
from home_assistant_bluetooth.models import BluetoothServiceInfoBleak as bti
from bleak import BleakScanner, BLEDevice, AdvertisementData
if platform.system() == "Linux":
    from bleak.assigned_numbers import AdvertisementDataType
    from bleak.backends.bluezdbus.scanner import BlueZScannerArgs
    from bleak.backends.bluezdbus.advertisement_monitor import OrPattern
from . import print_line, reporting_mode, sd_notifier, flores
from .mqtt import start_mqtt, found_mqtt, send_mqtt
from .xiaomi_parser import XiaomiBluetoothDeviceData

if platform.system() == "Linux":
    # or_patterns is a workaround for the fact that passive scanning
    # needs at least one matcher to be set. The below matcher
    # will match all devices.
    PASSIVE_SCANNER_ARGS = BlueZScannerArgs(
        or_patterns=[
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x06"),
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x1a"),
        ]
    )


CLOCK_MONOTONIC_COARSE = 6
devices = {}
unnamed_devices = {}


def get_time() -> float:
    """Gets coarse monotonic time"""
    if sys.platform != "win32":
        return time.clock_gettime(CLOCK_MONOTONIC_COARSE)
    return time.monotonic()


async def print_device(device: BLEDevice, data: AdvertisementData):
    """ Print device information """

    if device.name is not None and len(device.name) > 0:  # == "Flower care":
        already_found = devices.get(device.address)
        if already_found is None:
            devices[device.address] = device
            print_line(f"*** Found device: {device}", warning=True)
            if not flores.get(device.address) is None:
                flora = flores[device.address]
                print_line(f"*** Adding device: {device}", warning=True)
                flora.poller = 'bleak'
                flora.detected = date.today()
                flora.last_seen = date.today()
                flora.data: XiaomiBluetoothDeviceData = XiaomiBluetoothDeviceData()
                found_mqtt(flora["name_pretty"], flora)
                print_line(f"*** Added device: {device}", warning=True)

        if not flores.get(device.address) is None:
            flora = flores[device.address]
            service_info = bti.from_device_and_advertisement_data(device, data, 'bleak',
                                                                  datetime.now().timestamp(),
                                                                  True)
            print_line(f"uuids: {data.service_uuids}")
            sensor_update = flora.data.update(service_info)
            if len(sensor_update.entity_values):
                last_poll = None
                if flora["last_poll"] is not None:
                    last_poll = get_time()-flora["last_poll"]
                if flora.data.poll_needed(service_info, last_poll):
                    sensor_update = await flora.data.async_poll(device)
                    if len(sensor_update.entity_values):
                        flora["last_poll"] = get_time()
                send_mqtt(flora["name_pretty"], flora)
                flora.last_seen = date.today()
    else:
        if unnamed_devices.get(device.address) is None:
            if not flores.get(device.address) is None:
                print_line(f"Found device without name for {flores[device.address]['name_pretty']}: " +
                           "{device.address}", warning=True)
                service_info = bti.from_device_and_advertisement_data(device, data, 'bleak',
                                                                      datetime.now().timestamp(),
                                                                      True)
                flores[device.address].data.update(service_info)
                send_mqtt("unknown", flores[device.address])
            else:  # try to parse something
                service_info = bti.from_device_and_advertisement_data(device, data, 'bleak',
                                                                      datetime.now().timestamp(),
                                                                      True)
                print_line(f"Found new device without name: {service_info.manufacturer} " +
                           f"name:{service_info.name} address:{service_info.address} " +
                           f"rssi:{service_info.rssi} connectabe: {service_info.connectable} uuids: " +
                           f"{service_info.service_uuids}")
                if len(service_info.service_uuids) > 0:
                    if flores.get(device.address) is None:
                        mifl = OrderedDict()
                        mifl["stats"] = {"count": 0, "success": 0}
                        mifl["name_pretty"] = "unknown"
                        mifl.data = XiaomiBluetoothDeviceData()
                        flores[device.address] = mifl
                    else:
                        mifl = flores[device.address]
                    sensor_update = mifl.data.update(service_info)
                    if len(sensor_update.entity_values):
                        last_poll = None
                        if mifl["last_poll"] is not None:
                            last_poll = get_time()-mifl["last_poll"]
                        if mifl.data.poll_needed(service_info, last_poll):
                            sensor_update = await mifl.data.async_poll(device)
                            if len(sensor_update.entity_values):
                                mifl["last_poll"] = get_time()
                        send_mqtt("unknown", flores[device.address])
            unnamed_devices[device.address] = device


async def main():
    """ Main entry point of the app """

    stop_event = asyncio.Event()

    if reporting_mode in ['mqtt-json', 'mqtt-smarthome', 'homeassistant-mqtt',
                          'thingsboard-json', 'wirenboard-mqtt']:
        start_mqtt()

    sd_notifier.notify('READY=1')

    scanner_kwargs: dict[str, Any] = {"detection_callback": print_device}
    scanner_kwargs["scanning_mode"] = "passive"
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
