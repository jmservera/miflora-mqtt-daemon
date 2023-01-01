#!/usr/bin/env python3

import sys
import re
import json
import os.path

from time import time, sleep, localtime, strftime
from collections import OrderedDict
from colorama import init as colorama_init
from colorama import Fore, Back, Style

from miflora.miflora_poller import MiFloraPoller, MI_BATTERY, MI_CONDUCTIVITY, MI_LIGHT, MI_MOISTURE, MI_TEMPERATURE
from btlewrap import BluepyBackend, GatttoolBackend, BluetoothBackendException
from bluepy.btle import BTLEException
import sdnotify



















# MQTT connection

# Initialize Mi Flora sensors
flores = OrderedDict()
for [name, mac] in config['Sensors'].items():
    if not re.match("[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", mac.lower()):
        print_line('The MAC address "{}" seems to be in the wrong format. Please check your configuration'.format(mac), error=True, sd_notify=True)
        sys.exit(1)

    if '@' in name:
        name_pretty, location_pretty = name.split('@')
    else:
        name_pretty, location_pretty = name, ''
    name_clean = clean_identifier(name_pretty)
    location_clean = clean_identifier(location_pretty)

    flora = OrderedDict()
    print('Adding sensor to device list and testing connection ...')
    print('Name:          "{}"'.format(name_pretty))
    # print_line('Attempting initial connection to Mi Flora sensor "{}" ({})'.format(name_pretty, mac), console=False, sd_notify=True)

    flora_poller = MiFloraPoller(mac=mac, backend=BluepyBackend, cache_timeout=miflora_cache_timeout, adapter=used_adapter)
    flora['poller'] = flora_poller
    flora['name_pretty'] = name_pretty
    flora['mac'] = flora_poller._mac
    flora['refresh'] = sleep_period
    flora['location_clean'] = location_clean
    flora['location_pretty'] = location_pretty
    flora['stats'] = {"count": 0, "success": 0, "failure": 0}
    flora['firmware'] = "0.0.0"
    try:
        flora_poller.fill_cache()
        flora_poller.parameter_value(MI_LIGHT)
        flora['firmware'] = flora_poller.firmware_version()
    except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
        print_line('Initial connection to Mi Flora sensor "{}" ({}) failed due to exception: {}'.format(name_pretty, mac, e), error=True, sd_notify=True)
    else:
        print('Internal name: "{}"'.format(name_clean))
        print('Device name:   "{}"'.format(flora_poller.name()))
        print('MAC address:   {}'.format(flora_poller._mac))
        print('Firmware:      {}'.format(flora_poller.firmware_version()))
        print_line('Initial connection to Mi Flora sensor "{}" ({}) successful'.format(name_pretty, mac), sd_notify=True)
        if int(flora_poller.firmware_version().replace(".", "")) < 319:
            print_line('Mi Flora sensor with a firmware version before 3.1.9 is not supported. Please update now.'.format(name_pretty, mac), error=True, sd_notify=True)

    print()
    flores[name_clean] = flora

   sleep(0.5) # some slack for the publish roundtrip and callback function
    print()

print_line('Initialization complete, starting MQTT publish loop', console=False, sd_notify=True)


# Sensor data retrieval and publication
while True:
    for [flora_name, flora] in flores.items():
        data = OrderedDict()
        attempts = 2
        flora['poller']._cache = None
        flora['poller']._last_read = None
        flora['stats']['count'] += 1
        print_line('Retrieving data from sensor "{}" ...'.format(flora['name_pretty']))
        while attempts != 0 and not flora['poller']._cache:
            try:
                flora['poller'].fill_cache()
                flora['poller'].parameter_value(MI_LIGHT)
            except (IOError, BluetoothBackendException, BTLEException, RuntimeError, BrokenPipeError) as e:
                attempts -= 1
                if attempts > 0:
                    if len(str(e)) > 0:
                        print_line('Retrying due to exception: {}'.format(e), error=True)
                    else:
                        print_line('Retrying ...', warning=True)
                flora['poller']._cache = None
                flora['poller']._last_read = None

        if not flora['poller']._cache:
            flora['stats']['failure'] += 1
            if reporting_mode == 'mqtt-homie':
                mqtt_client[flora_name.lower()].publish('{}/{}/$state'.format(base_topic, flora_name.lower()), 'disconnected', 1, True)
            print_line('Failed to retrieve data from Mi Flora sensor "{}" ({}), success rate: {:.0%}'.format(
                flora['name_pretty'], flora['mac'], flora['stats']['success']/flora['stats']['count']
                ), error = True, sd_notify = True)
            print()
            continue
        else:
            flora['stats']['success'] += 1

        for param,_ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        print_line('Result: {}'.format(json.dumps(data)))

        if reporting_mode == 'mqtt-json':
            print_line('Publishing to MQTT topic "{}/{}"'.format(base_topic, flora_name))
            mqtt_client.publish('{}/{}'.format(base_topic, flora_name), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'thingsboard-json':
            print_line('Publishing to MQTT topic "{}" username "{}"'.format(base_topic, flora_name))
            mqtt_client.username_pw_set(flora_name)
            mqtt_client.reconnect()
            sleep(1.0)
            mqtt_client.publish('{}'.format(base_topic), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'homeassistant-mqtt':
            print_line('Publishing to MQTT topic "{}/sensor/{}/state"'.format(base_topic, flora_name.lower()))
            mqtt_client.publish('{}/sensor/{}/state'.format(base_topic, flora_name.lower()), json.dumps(data), retain=True)
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'gladys-mqtt':
            print_line('Publishing to MQTT topic "{}/mqtt:miflora:{}/feature"'.format(base_topic, flora_name.lower()))
            mqtt_client.publish('{}/mqtt:miflora:{}/feature'.format(base_topic, flora_name.lower()), json.dumps(data))
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'mqtt-homie':
            print_line('Publishing data to MQTT base topic "{}/{}"'.format(base_topic, flora_name.lower()))
            mqtt_client[flora_name.lower()].publish('{}/{}/$state'.format(base_topic, flora_name.lower()), 'ready', 1, True)
            for [param, value] in data.items():
                mqtt_client[flora_name.lower()].publish('{}/{}/sensor/{}'.format(base_topic, flora_name.lower(), param), value, 1, True)
            mqtt_client[flora_name.lower()].publish('{}/{}/$stats/timestamp'.format(base_topic, flora_name.lower()), strftime('%Y-%m-%dT%H:%M:%S%z', localtime()), 1, True)
            sleep(0.5) # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'mqtt-smarthome':
            for [param, value] in data.items():
                print_line('Publishing data to MQTT topic "{}/status/{}/{}"'.format(base_topic, flora_name, param))
                payload = dict()
                payload['val'] = value
                payload['ts'] = int(round(time() * 1000))
                mqtt_client.publish('{}/status/{}/{}'.format(base_topic, flora_name, param), json.dumps(payload), retain=True)
            sleep(0.5)  # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'wirenboard-mqtt':
            for [param, value] in data.items():
                print_line('Publishing data to MQTT topic "/devices/{}/controls/{}"'.format(flora_name, param))
                mqtt_client.publish('/devices/{}/controls/{}'.format(flora_name, param), value, retain=True)
            mqtt_client.publish('/devices/{}/controls/{}'.format(flora_name, 'timestamp'), strftime('%Y-%m-%d %H:%M:%S', localtime()), retain=True)
            sleep(0.5)  # some slack for the publish roundtrip and callback function
        elif reporting_mode == 'json':
            data['timestamp'] = strftime('%Y-%m-%d %H:%M:%S', localtime())
            data['name'] = flora_name
            data['name_pretty'] = flora['name_pretty']
            data['mac'] = flora['mac']
            data['firmware'] = flora['firmware']
            print('Data for "{}": {}'.format(flora_name, json.dumps(data)))
        else:
            raise NameError('Unexpected reporting_mode.')
        print()

    print_line('Status messages published', console=False, sd_notify=True)

    if daemon_enabled:
        print_line('Sleeping ({} seconds) ...'.format(sleep_period))
        sleep(sleep_period)
        print()
    else:
        print_line('Execution finished in non-daemon-mode', sd_notify=True)
        if reporting_mode == 'mqtt-json':
            mqtt_client.disconnect()
        break
