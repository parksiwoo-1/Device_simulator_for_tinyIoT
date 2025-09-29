"""Configuration for the oneM2M device simulator (HTTP/MQTT endpoints and sensors)."""

# oneM2M CSE identity used by both transports
CSE_NAME = "tinyiot"  # csi (used in MQTT topic)
CSE_RN = "TinyIoT"    # rn  (used in MQTT payload "to")

# HTTP (REST) endpoint configuration
# configure for your environment
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 3000
HTTP_BASE = f"http://{HTTP_HOST}:{HTTP_PORT}"
BASE_URL_RN = f"{HTTP_BASE}/{CSE_RN}"

# Baseline HTTP headers used for registration requests
# configure for your environment
HTTP_DEFAULT_HEADERS = {
    "Accept": "application/json",
    "X-M2M-Origin": "CAdmin",
    "X-M2M-RVI": "3",
    "X-M2M-RI": "req",
}

# Headers for tree inspection calls (no payload type)
# configure for your environment
HTTP_GET_HEADERS = {
    "Accept": "application/json",
    "X-M2M-Origin": "CAdmin",
    "X-M2M-RVI": "3",
    "X-M2M-RI": "check",
}

# Mapping between logical resource types and the oneM2M type code
# configure for your environment
HTTP_CONTENT_TYPE_MAP = {
    "ae": 2,
    "cnt": 3,
    "cin": 4,
}

# Per-sensor resource registration metadata used by build_sensor_meta
# configure for your environment
SENSOR_RESOURCES = {
    "temp": {
        "ae": "CtempSensor",
        "cnt": "temperature",
        "api": "N.temp",
        "origin": "CtempSensor",
    },
    "humid": {
        "ae": "ChumidSensor",
        "cnt": "humidity",
        "api": "N.humid",
        "origin": "ChumidSensor",
    },
    "co2": {
        "ae": "Cco2Sensor",
        "cnt": "co2",
        "api": "N.co2",
        "origin": "Cco2Sensor",
    },
    "soil": {
        "ae": "CsoilSensor",
        "cnt": "soil",
        "api": "N.soil",
        "origin": "CsoilSensor",
    },
}

# Template used when SENSOR_RESOURCES does not define a sensor explicitly
GENERIC_SENSOR_TEMPLATE = {
    "ae": "C{sensor}Sensor",
    "cnt": "{sensor}",
    "api": "N.{sensor}",
    "origin": "C{sensor}Sensor",
}

# MQTT (Mosquitto) broker configuration
# configure for your environment
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883  # integer

# Shared timeout/retry knobs for both transports
CONNECT_TIMEOUT = 2       # socket/connect timeout (seconds)
READ_TIMEOUT = 10         # HTTP read timeout (seconds)
RETRY_WAIT_SECONDS = 5    # wait before retry after a send failure (seconds)
SEND_ERROR_THRESHOLD = 5  # max consecutive send failures before stopping

# Default oneM2M container retention limits
CNT_MNI = 1000       # max number of instances
CNT_MBS = 10485760   # max byte size

# Default CSV fixtures used when sensors run in CSV mode
# configure for your environment
TEMP_CSV = "/home/parks/tinyIoT/simulator/smartfarm_data/temperature_data.csv"
HUMID_CSV = "/home/parks/tinyIoT/simulator/smartfarm_data/humidity_data.csv"
CO2_CSV = "/home/parks/tinyIoT/simulator/smartfarm_data/co2_data.csv"
SOIL_CSV = "/home/parks/tinyIoT/simulator/smartfarm_data/soil_data.csv"

# Random-generation profiles for supported sensors (random mode)
TEMP_PROFILE = {
    "data_type": "float",  # "int" | "float" | "string"
    "min": 20.0,
    "max": 35.0,
}

HUMID_PROFILE = {
    "data_type": "float",  # "int" | "float" | "string"
    "min": 50,
    "max": 90,
}

CO2_PROFILE = {
    "data_type": "float",  # "int" | "float" | "string"
    "min": 350,
    "max": 800,
}

SOIL_PROFILE = {
    "data_type": "float",  # "int" | "float" | "string"
    "min": 20,
    "max": 60,
}
