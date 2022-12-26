"""MQTT Module for miflora-mqtt-daemon."""
import os
import sys
import ssl
import socket
from time import sleep
import paho.mqtt.client as mqtt
from . import (print_line,
               reporting_mode,
               config,
               base_topic,
               miflora_cache_timeout)


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


def send_mqtt(data):
    """Send data to MQTT broker."""
    MQTT_CLIENT.publish(f'{base_topic}/temperature',
                        payload=data)


def found_mqtt(data):
    """Send data to MQTT broker."""
    MQTT_CLIENT.publish(f'{base_topic}/found',
                        payload=data)