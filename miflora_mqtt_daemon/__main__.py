""" Description: Main entry point for the miflora-mqtt-daemon
"""
import sys
import time
from typing import Any
import asyncio
import platform
from home_assistant_bluetooth.models import BluetoothServiceInfoBleak as bti
from bleak import BleakScanner, BLEDevice, AdvertisementData
from bleak.assigned_numbers import AdvertisementDataType
from bleak.backends.bluezdbus.scanner import BlueZScannerArgs
from bleak.backends.bluezdbus.advertisement_monitor import OrPattern
from . import print_line, reporting_mode, sd_notifier, flores
from .mqtt import start_mqtt, found_mqtt, send_mqtt
from .xiaomi_parser import XiaomiBluetoothDeviceData

CLOCK_MONOTONIC_COARSE = 6
devices = {}
unnamed_devices = {}


def get_time() -> float:
    """Gets coarse monotonic time"""
    return time.clock_gettime(CLOCK_MONOTONIC_COARSE)


async def process_device(device: BLEDevice, data: AdvertisementData):
    """ Use device information for announcing it via mqtt."""

    if device.name is not None and len(device.name) > 0:  # == "Flower care":
        already_found = devices.get(device.address)
        if already_found is None:
            devices[device.address] = device
            if not flores.get(device.address) is None:
                flora = flores[device.address]
                print_line(f"Adding device: {device.address} {device.name}")
                flora["poller"] = 'bleak'
                flora.data: XiaomiBluetoothDeviceData = XiaomiBluetoothDeviceData()
                found_mqtt(flora["name_pretty"], flora)
                print_line(f"Added device: {device}")
            elif device.name == "Flower care":
                print_line(f"Device {device} found but not configured", warning=True, sd_notify=True)
            else:
                print_line(f"Unknown device announced: {device}")

        if not flores.get(device.address) is None:
            flora = flores[device.address]
            service_info = bti.from_device_and_advertisement_data(device, data, 'bleak',
                                                                  get_time(),
                                                                  True)
            sensor_update = flora.data.update(service_info)
            if len(sensor_update.entity_values):
                last_poll = None

                if flora.get("last_poll") is not None:
                    last_poll = get_time()-flora["last_poll"]
                if flora.data.poll_needed(service_info, last_poll):
                    old_fw = flora.data.firmware
                    sensor_update = await flora.data.async_poll(device)
                    if len(sensor_update.entity_values):
                        flora["last_poll"] = get_time()
                        if old_fw != flora.data.firmware:
                            # when we get the fw version update the
                            # mqtt announcement
                            found_mqtt(flora["name_pretty"], flora)
                send_mqtt(flora["name_pretty"], flora)


async def main():
    """ Main entry point of the app """
    stop_event = asyncio.Event()

    if reporting_mode in ['mqtt-json', 'mqtt-smarthome', 'homeassistant-mqtt',
                          'thingsboard-json', 'wirenboard-mqtt']:
        start_mqtt()

    sd_notifier.notify('READY=1')

    # or_patterns is a workaround for the fact that passive scanning
    # needs at least one matcher to be set. The below matcher
    # will match all devices.
    async with BleakScanner(process_device, scanning_mode="passive",
                            bluez=dict(
                                or_patterns=[
                                    (0, AdvertisementDataType.FLAGS, b"\x06"),
                                    (0, AdvertisementDataType.FLAGS, b"\x1a"),
                                ])
                            ) as scanner:
        print_line("Starting BLE passive scanner...", sd_notify=True)
        await scanner.start()
        print_line("BLE passive scanner started.", sd_notify=True)
        try:
            await stop_event.wait()
        finally:
            print_line("Stopping scanner...", sd_notify=True)
            await scanner.stop()
            print_line("Scanner stopped...", sd_notify=True)


if __name__ == "__main__":
    asyncio.run(main())
