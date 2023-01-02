"""MQTT Module for miflora-mqtt-daemon."""
from collections import OrderedDict
import os
import sys
import ssl
import json
from time import localtime, sleep, strftime
import paho.mqtt.client as mqtt
from . import (print_line,
               reporting_mode,
               config,
               base_topic,
               #  miflora_cache_timeout,
               sleep_period)

MI_TEMPERATURE = "temperature"
MI_LIGHT = "illuminance"
MI_MOISTURE = "moisture"
MI_CONDUCTIVITY = "conductivity"
MI_BATTERY = "battery"

parameters = OrderedDict([
    (MI_LIGHT, dict(name="LightIntensity", name_pretty='Sunlight Intensity', typeformat='%d',
     unit='lux', device_class="illuminance", state_class="measurement")),
    (MI_TEMPERATURE, dict(name="AirTemperature", name_pretty='Air Temperature', typeformat='%.1f',
     unit='°C', device_class="temperature", state_class="measurement")),
    (MI_MOISTURE, dict(name="SoilMoisture", name_pretty='Soil Moisture', typeformat='%d',
     unit='%', device_class="humidity", state_class="measurement")),
    (MI_CONDUCTIVITY, dict(name="SoilConductivity", name_pretty='Soil Conductivity/Fertility',
     typeformat='%d', unit='µS/cm', state_class="measurement")),
    (MI_BATTERY, dict(name="Battery", name_pretty='Sensor Battery Level',
     typeformat='%d', unit='%', device_class="battery", state_class="measurement"))
])


def on_connect(client, userdata, flags, response_code):
    # pylint: disable=unused-argument
    """Callback function for MQTT connection.
       see: # Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
    """
    if response_code == 0:
        print_line('MQTT connection established', console=True, sd_notify=True)
    else:
        print_line(f'Connection error with result code {str(response_code)} ' +
                   f'- {mqtt.connack_string(response_code)}', error=True)
        # kill main thread
        os._exit(1)  # pylint: disable=protected-access


def on_publish(client, userdata, mid):
    # print_line('Data successfully published.')
    pass


MQTT_CLIENT = mqtt.Client()


def start_mqtt():
    """Configure MQTT connection and start."""
    print_line('Connecting to MQTT broker ...')
    MQTT_CLIENT.on_connect = on_connect
    MQTT_CLIENT.on_publish = on_publish
    if reporting_mode == 'mqtt-json':
        MQTT_CLIENT.will_set(f'{base_topic}/$announce', payload='{}',
                             retain=True)
    elif reporting_mode == 'mqtt-smarthome':
        MQTT_CLIENT.will_set(f'{base_topic}/connected', payload='0',
                             retain=True)

    if config['MQTT'].getboolean('tls', False):
        # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest
        # protocol version that both the client and server support. Despite the
        # name, this option can select “TLS” protocols as well as “SSL”" - so
        # this seems like a resonable default
        MQTT_CLIENT.tls_set(
            ca_certs=config['MQTT'].get('tls_ca_cert', None),
            keyfile=config['MQTT'].get('tls_keyfile', None),
            certfile=config['MQTT'].get('tls_certfile', None),
            tls_version=ssl.PROTOCOL_SSLv23
        )

    mqtt_username = os.environ.get("MQTT_USERNAME",
                                   config['MQTT'].get('username'))
    mqtt_password = os.environ.get("MQTT_PASSWORD",
                                   config['MQTT'].get('password', None))

    if mqtt_username:
        MQTT_CLIENT.username_pw_set(mqtt_username, mqtt_password)
    try:
        MQTT_CLIENT.connect(os.environ.get('MQTT_HOSTNAME',
                            config['MQTT'].get('hostname', 'localhost')),
                            port=int(os.environ.get('MQTT_PORT',
                                     config['MQTT'].get('port', '1883'))),
                            keepalive=config['MQTT'].getint('keepalive', 60))
    except (ValueError, OSError,  # ssl.CertificateError,
            ConnectionError) as mqtt_error:
        print_line(f'{mqtt_error}', error=True, sd_notify=True)
        print_line('MQTT connection error. Please check your settings in ' +
                   'the configuration file "config.ini".', error=True,
                   sd_notify=True)
        sys.exit(1)
    else:
        if reporting_mode == 'mqtt-smarthome':
            MQTT_CLIENT.publish(f'{base_topic}/connected', payload='1',
                                retain=True)
        if reporting_mode != 'thingsboard-json':
            MQTT_CLIENT.loop_start()
            sleep(1.0)  # some slack to establish the connection


def send_mqtt(flora_name: str, flora: OrderedDict):
    """Send data to MQTT broker."""
    data = OrderedDict()
    # attempts = 2
    # flora['poller']._cache = None
    # flora['poller']._last_read = None
    flora['stats']['count'] += 1
    flora['stats']['success'] += 1

    # for param, _ in parameters.items():
    #     data[param] = flora['poller'].parameter_value(param)
    # print_line('Result: {}'.format(json.dumps(data)))
    data = {}
    for key, value in flora.data._sensor_values.items():
        data[key.key] = value.native_value

    if reporting_mode == 'mqtt-json':
        print_line('Publishing to MQTT topic "{}/{}"'.format(base_topic, flora_name))
        MQTT_CLIENT.publish('{}/{}'.format(base_topic, flora_name), json.dumps(data))
        sleep(0.5) # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'thingsboard-json':
        print_line('Publishing to MQTT topic "{}" username "{}"'.format(base_topic, flora_name))
        MQTT_CLIENT.username_pw_set(flora_name)
        MQTT_CLIENT.reconnect()
        sleep(1.0)
        MQTT_CLIENT.publish('{}'.format(base_topic), json.dumps(data))
        sleep(0.5) # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'homeassistant-mqtt':
        print_line('Publishing to MQTT topic "{}/sensor/{}/state"'.format(base_topic, flora_name.lower()))
        MQTT_CLIENT.publish('{}/sensor/{}/state'.format(base_topic, flora_name.lower()), json.dumps(data), retain=True)
        sleep(0.5) # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'gladys-mqtt':
        print_line('Publishing to MQTT topic "{}/mqtt:miflora:{}/feature"'.format(base_topic, flora_name.lower()))
        MQTT_CLIENT.publish('{}/mqtt:miflora:{}/feature'.format(base_topic, flora_name.lower()), json.dumps(data))
        sleep(0.5) # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'mqtt-homie':
        print_line('Publishing data to MQTT base topic "{}/{}"'.format(base_topic, flora_name.lower()))
        mqtt_clients[flora_name.lower()].publish('{}/{}/$state'.format(base_topic, flora_name.lower()), 'ready', 1, True)
        for [param, value] in data.items():
            mqtt_clients[flora_name.lower()].publish('{}/{}/sensor/{}'.format(base_topic, flora_name.lower(), param), value, 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/{}/$stats/timestamp'.format(base_topic, flora_name.lower()), strftime('%Y-%m-%dT%H:%M:%S%z', localtime()), 1, True)
        sleep(0.5) # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'mqtt-smarthome':
        for [param, value] in data.items():
            print_line('Publishing data to MQTT topic "{}/status/{}/{}"'.format(base_topic, flora_name, param))
            payload = dict()
            payload['val'] = value
            payload['ts'] = int(round(time() * 1000))
            MQTT_CLIENT.publish('{}/status/{}/{}'.format(base_topic, flora_name, param), json.dumps(payload), retain=True)
        sleep(0.5)  # some slack for the publish roundtrip and callback function
    elif reporting_mode == 'wirenboard-mqtt':
        for [param, value] in data.items():
            print_line('Publishing data to MQTT topic "/devices/{}/controls/{}"'.format(flora_name, param))
            MQTT_CLIENT.publish('/devices/{}/controls/{}'.format(flora_name, param), value, retain=True)
        MQTT_CLIENT.publish('/devices/{}/controls/{}'.format(flora_name, 'timestamp'), strftime('%Y-%m-%d %H:%M:%S', localtime()), retain=True)
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


mqtt_clients: dict[str, mqtt.Client] = dict()


def found_mqtt(flora_name: str, flora: OrderedDict):
    """Send data to MQTT broker."""
    # Discovery Announcement
    if reporting_mode == 'mqtt-json':
        print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
        flores_info = dict()
        flora_info = {key: value for key, value in flora.items() if key not in ['poller', 'stats']}
        flora_info['topic'] = '{}/{}'.format(base_topic, flora_name)
        flores_info[flora_name] = flora_info
        MQTT_CLIENT.publish('{}/$announce'.format(base_topic), json.dumps(flores_info), retain=True)
        sleep(0.5)  # some slack for the publish roundtrip and callback function
        print()
    elif reporting_mode == 'mqtt-homie':
        global mqtt_clients
        print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')

        print_line('Connecting to MQTT broker for "{}" ...'.format(flora['name_pretty']))
        mqtt_clients[flora_name.lower()] = mqtt.Client(flora_name.lower())
        mqtt_clients[flora_name.lower()].on_connect = on_connect
        mqtt_clients[flora_name.lower()].on_publish = on_publish
        mqtt_clients[flora_name.lower()].will_set('{}/{}/$state'.format(base_topic, flora_name.lower()), payload='disconnected', retain=True)

        if config['MQTT'].getboolean('tls', False):
            # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
            # that both the client and server support. Despite the name, this option can select
            # “TLS” protocols as well as “SSL”" - so this seems like a resonable default
            mqtt_clients[flora_name.lower()].tls_set(
                ca_certs=config['MQTT'].get('tls_ca_cert', None),
                keyfile=config['MQTT'].get('tls_keyfile', None),
                certfile=config['MQTT'].get('tls_certfile', None),
                tls_version=ssl.PROTOCOL_SSLv23
            )

        mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
        mqtt_password = os.environ.get("MQTT_PASSWORD", config['MQTT'].get('password', None))

        if mqtt_username:
            mqtt_clients[flora_name.lower()].username_pw_set(mqtt_username, mqtt_password)
        try:
            mqtt_clients[flora_name.lower()].connect(os.environ.get('MQTT_HOSTNAME',
                                                     config['MQTT'].get('hostname', 'localhost')),
                                                     port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port',
                                                                                                             '1883'))),
                                                     keepalive=config['MQTT'].getint('keepalive', 60))
        except:
            print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"',
                       error=True, sd_notify=True)
            sys.exit(1)
        else:
            mqtt_clients[flora_name.lower()].loop_start()
            sleep(1.0) # some slack to establish the connection

        topic_path = '{}/{}'.format(base_topic, flora_name.lower())

        mqtt_clients[flora_name.lower()].publish('{}/$homie'.format(topic_path), '3.0', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$name'.format(topic_path), flora['name_pretty'], 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$state'.format(topic_path), 'ready', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$mac'.format(topic_path), flora['mac'], 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$stats'.format(topic_path), 'interval,timestamp', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$stats/interval'.format(topic_path), flora['refresh'], 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$stats/timestamp'.format(topic_path), strftime('%Y-%m-%dT%H:%M:%S%z', localtime()), 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$fw/name'.format(topic_path), 'miflora-firmware', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$fw/version'.format(topic_path), flora['firmware'], 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$nodes'.format(topic_path), 'sensor', 1, True)

        sensor_path = '{}/sensor'.format(topic_path)

        mqtt_clients[flora_name.lower()].publish('{}/$name'.format(sensor_path), 'miflora', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/$properties'.format(sensor_path), 'battery,conductivity,light,moisture,temperature', 1, True)

        mqtt_clients[flora_name.lower()].publish('{}/battery/$name'.format(sensor_path), 'battery', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/battery/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/battery/$unit'.format(sensor_path), '%', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/battery/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/battery/$format'.format(sensor_path), '0:100', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/battery/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$name'.format(sensor_path), 'conductivity', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$unit'.format(sensor_path), 'µS/cm', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$format'.format(sensor_path), '0:*', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/conductivity/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_clients[flora_name.lower()].publish('{}/light/$name'.format(sensor_path), 'light', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/light/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/light/$unit'.format(sensor_path), 'lux', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/light/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/light/$format'.format(sensor_path), '0:50000', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/light/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_clients[flora_name.lower()].publish('{}/moisture/$name'.format(sensor_path), 'moisture', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/moisture/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/moisture/$unit'.format(sensor_path), '%', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/moisture/$datatype'.format(sensor_path), 'integer', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/moisture/$format'.format(sensor_path), '0:100', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/moisture/$retained'.format(sensor_path), 'true', 1, True)

        mqtt_clients[flora_name.lower()].publish('{}/temperature/$name'.format(sensor_path), 'temperature', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/temperature/$settable'.format(sensor_path), 'false', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/temperature/$unit'.format(sensor_path), '°C', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/temperature/$datatype'.format(sensor_path), 'float', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/temperature/$format'.format(sensor_path), '*', 1, True)
        mqtt_clients[flora_name.lower()].publish('{}/temperature/$retained'.format(sensor_path), 'true', 1, True)
        sleep(0.5) # some slack for the publish roundtrip and callback function
        print()
    elif reporting_mode == 'homeassistant-mqtt':
        print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
        state_topic = '{}/sensor/{}/state'.format(base_topic, flora_name.lower())
        for [sensor, params] in parameters.items():
            discovery_topic = 'homeassistant/sensor/{}/{}/config'.format(flora_name.lower(), sensor)
            payload = OrderedDict()
            payload['name'] = "{} {}".format(flora_name, sensor.title())
            payload['unique_id'] = "{}-{}".format(flora['mac'].lower().replace(":", ""), sensor)
            payload['unit_of_measurement'] = params['unit']
            if 'device_class' in params:
                payload['device_class'] = params['device_class']
            if 'state_class' in params:
                payload['state_class'] = params['state_class']
            payload['state_topic'] = state_topic
            payload['value_template'] = "{{{{ value_json.{} }}}}".format(sensor)
            payload['device'] = {
                    'identifiers' : ["MiFlora{}".format(flora['mac'].lower().replace(":", ""))],
                    'connections' : [["mac", flora['mac'].lower()]],
                    'manufacturer' : 'Xiaomi',
                    'name' : flora_name,
                    'model' : 'MiFlora Plant Sensor (HHCCJCY01)',
                    'sw_version': flora.data.firmware
            }
            payload['expire_after'] = str(int(sleep_period * 1.5))
            MQTT_CLIENT.publish(discovery_topic, json.dumps(payload), 1, True)
    elif reporting_mode == 'gladys-mqtt':
        print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
        topic_path = '{}/mqtt:miflora:{}/feature'.format(base_topic, flora_name.lower())
        data = OrderedDict()
        for param, _ in parameters.items():
            data[param] = flora['poller'].parameter_value(param)
        MQTT_CLIENT.publish('{}/mqtt:battery/state'.format(topic_path), data['battery'], 1, True)
        MQTT_CLIENT.publish('{}/mqtt:moisture/state'.format(topic_path), data['moisture'], 1, True)
        MQTT_CLIENT.publish('{}/mqtt:light/state'.format(topic_path), data['light'], 1, True)
        MQTT_CLIENT.publish('{}/mqtt:conductivity/state'.format(topic_path), data['conductivity'], 1, True)
        MQTT_CLIENT.publish('{}/mqtt:temperature/state'.format(topic_path), data['temperature'], 1, True)

        sleep(0.5)  # some slack for the publish roundtrip and callback function
        print()
    elif reporting_mode == 'wirenboard-mqtt':
        print_line('Announcing Mi Flora devices to MQTT broker for auto-discovery ...')
        MQTT_CLIENT.publish('/devices/{}/meta/name'.format(flora_name), flora_name, 1, True)
        topic_path = '/devices/{}/controls'.format(flora_name)
        MQTT_CLIENT.publish('{}/battery/meta/type'.format(topic_path), 'value', 1, True)
        MQTT_CLIENT.publish('{}/battery/meta/units'.format(topic_path), '%', 1, True)
        MQTT_CLIENT.publish('{}/conductivity/meta/type'.format(topic_path), 'value', 1, True)
        MQTT_CLIENT.publish('{}/conductivity/meta/units'.format(topic_path), 'µS/cm', 1, True)
        MQTT_CLIENT.publish('{}/light/meta/type'.format(topic_path), 'value', 1, True)
        MQTT_CLIENT.publish('{}/light/meta/units'.format(topic_path), 'lux', 1, True)
        MQTT_CLIENT.publish('{}/moisture/meta/type'.format(topic_path), 'rel_humidity', 1, True)
        MQTT_CLIENT.publish('{}/temperature/meta/type'.format(topic_path), 'temperature', 1, True)
        MQTT_CLIENT.publish('{}/timestamp/meta/type'.format(topic_path), 'text', 1, True)
