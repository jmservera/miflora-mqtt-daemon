""" Description: Main entry point for the miflora-mqtt-daemon
"""

import asyncio
from collections import OrderedDict
from bleak import BleakScanner, BLEDevice, AdvertisementData
from . import print_line, reporting_mode, sd_notifier, flores
from .mqtt import start_mqtt, found_mqtt, send_mqtt

devices = {}


async def print_device(device: BLEDevice, data: AdvertisementData):
    """ Print device information """

    if device.name is not None and len(device.name)>0: #== "Flower care":
        flora = devices.get(device.address)
        if flora is None:
            devices[device.address] = device
            print_line(f"*** Found device: {device}", warning=True)
            if not flores.get(device.address) is None:
                flora = flores[device.address]
                found_mqtt(f'{flora["name_pretty"]}@{flora["location_pretty"]}')
                print_line(f"*** Adding device: {device}", warning=True)
                flores[device.address].poller = 'bleak'
                print_line(f"*** Added device: {device}", warning=True)
        if not flores.get(device.address) is None:
            flores[device.address].data = data
            print_line(f"Data retrieved for {device.address}")
            send_mqtt(flores[device.address].name_pretty)


async def main():
    """ Main entry point of the app """

    if reporting_mode in ['mqtt-json', 'mqtt-smarthome', 'homeassistant-mqtt',
                          'thingsboard-json', 'wirenboard-mqtt']:
        start_mqtt()

    sd_notifier.notify('READY=1')

    scanner = BleakScanner(print_device)
    print_line("Starting BLE passive scanner...")
    await scanner.start()
    print_line("BLE passive scanner started.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print_line("Stopping scanner...")
        await scanner.stop()
        print_line("Scanner stopped...")


if __name__ == "__main__":
    asyncio.run(main())
