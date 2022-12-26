# follow https://aglowiditsolutions.com/blog/python-best-practices/
import signal
import sys
import os
import re
from collections import OrderedDict
from time import localtime, strftime
import argparse
from configparser import ConfigParser
from colorama import Fore, Style
from colorama import init as colorama_init
from unidecode import unidecode
import sdnotify

if False:  # pylint: disable=using-constant-test
    # will be caught by python 2.7 to be illegal syntax
    print('Sorry, this script requires a python3 runtime environment.',
          file=sys.stderr)

PROJECT_NAME = 'Xiaomi Mi Flora Plant Sensor MQTT Client/Daemon'
PROJECT_URL = 'https://github.com/ThomDietrich/miflora-mqtt-daemon'
PROJECT_VERSION = '1.2.0-alpha'

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

WHITELIST = False


# Logging function
def print_line(text, error=False, warning=False, sd_notify=False, console=True):
    """Print a line to the console and/or systemd service notification."""
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(f'{Fore.RED + Style.BRIGHT}{[timestamp]} {Style.RESET_ALL}' +
                  f'{text}{Style.RESET_ALL}', file=sys.stderr)
        elif warning:
            print(f'{Fore.YELLOW}{[timestamp]} {Style.RESET_ALL}' +
                  f'{text}{Style.RESET_ALL}')
        else:
            print(f'{Fore.GREEN}{[timestamp]} {Style.RESET_ALL}' +
                  f'{text}{Style.RESET_ALL}')
    timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
    if sd_notify:
        sd_notifier.notify(f'STATUS={timestamp_sd} - {unidecode(text)}.')


def clean_identifier(name: str) -> str:
    """Clean up a string to be used as an identifier.
       Removes non-ascii characters and replaces spaces with dashes."""
    clean = name.strip()
    for this, that in [[' ', '-'], ['ä', 'ae'], ['Ä', 'Ae'], ['ö', 'oe'],
                       ['Ö', 'Oe'], ['ü', 'ue'], ['Ü', 'Ue'], ['ß', 'ss']]:
        clean = clean.replace(this, that)
    clean = unidecode(clean)
    return clean


try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except AttributeError:
    pass  # Windows


colorama_init()
print(Fore.GREEN + Style.BRIGHT)
print(PROJECT_NAME)
print('Source:', PROJECT_URL)
print(Style.RESET_ALL)

# Argparse
parser = argparse.ArgumentParser(description=PROJECT_NAME,
                                 epilog='For further details see: '
                                 + PROJECT_URL)
parser.add_argument('--config_dir',
                    help='set directory where config.ini is located',
                    default=sys.path[0])
parse_args = parser.parse_args()

# Load configuration file
config_dir = parse_args.config_dir

config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True,
               sd_notify=True)
    sys.exit(1)

reporting_mode = config['General'].get('reporting_method', 'mqtt-json')
used_adapter = config['General'].get('adapter', 'hci0')
daemon_enabled = config['Daemon'].getboolean('enabled', True)

if reporting_mode == 'mqtt-homie':
    DEFAULT_BASE_TOPIC = 'homie'
elif reporting_mode == 'homeassistant-mqtt':
    DEFAULT_BASE_TOPIC = 'homeassistant'
elif reporting_mode == 'thingsboard-json':
    DEFAULT_BASE_TOPIC = 'v1/devices/me/telemetry'
elif reporting_mode == 'wirenboard-mqtt':
    DEFAULT_BASE_TOPIC = ''
else:
    DEFAULT_BASE_TOPIC = 'miflora'

base_topic = config['MQTT'].get('base_topic', DEFAULT_BASE_TOPIC).lower()
sleep_period = config['Daemon'].getint('period', 300)
miflora_cache_timeout = sleep_period - 1

# Check configuration
if reporting_mode not in ['mqtt-json', 'mqtt-homie', 'json', 'mqtt-smarthome',
                          'homeassistant-mqtt', 'thingsboard-json',
                          'wirenboard-mqtt']:
    print_line('Configuration parameter reporting_mode set to an invalid ' +
               'value', error=True, sd_notify=True)
    sys.exit(1)
else:
    print_line('Reporting mode: ' + reporting_mode)
if not config['Sensors']:
    print_line('No sensors found in configuration file "config.ini". All ' +
               'detected sensors will be allowed.', warning=True)
if reporting_mode == 'wirenboard-mqtt' and base_topic:
    print_line('Parameter "base_topic" ignored for "reporting_method = ' +
               'wirenboard-mqtt"', warning=True, sd_notify=True)

print_line('Configuration accepted', console=False, sd_notify=True)

flores = OrderedDict()

for [name, mac] in config['Sensors'].items():
    EXPRESSION = r'[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:' + \
                 r'[0-9a-f]{2}:[0-9a-f]{2}'
    if not re.match(EXPRESSION, mac.lower()):
        print_line(f'The MAC address {mac} seems to be in the wrong format.' +
                   'Please check your configuration', error=True,
                   sd_notify=True)
        sys.exit(1)

    if '@' in name:
        name_pretty, location_pretty = name.split('@')
    else:
        name_pretty, location_pretty = name, ''
    name_clean = clean_identifier(name_pretty)
    location_clean = clean_identifier(location_pretty)

    flora = OrderedDict()
    print('Adding sensor to device list ...')
    print(f'Name:          "{name_pretty}"')

    flora['poller'] = None
    flora['name_pretty'] = name_pretty
    flora['mac'] = mac
    flora['refresh'] = sleep_period
    flora['location_clean'] = location_clean
    flora['location_pretty'] = location_pretty
    flora['stats'] = {"count": 0, "success": 0, "failure": 0}
    flora['firmware'] = "0.0.0"

    flores[mac] = flora
    WHITELIST = True  # Allows only listed sensors to be used
