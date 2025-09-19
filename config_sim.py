# oneM2M CSE
CSE_NAME = "tinyiot"   # csi (used in MQTT topic)
CSE_RN   = "TinyIoT"   # rn  (used in MQTT payload "to")

# HTTP (REST)
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 3000
HTTP_BASE = f"http://{HTTP_HOST}:{HTTP_PORT}"

# MQTT (Mosquitto)
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883  # integer

# Timeouts & retry (moved from simulator.py)
CONNECT_TIMEOUT       = 2    # socket/connect timeout (seconds)
READ_TIMEOUT          = 10   # HTTP read timeout (seconds)
RETRY_WAIT_SECONDS    = 5    # wait before retry after a send failure (seconds)
SEND_ERROR_THRESHOLD  = 5    # max consecutive send failures before stopping

# oneM2M container limits
CNT_MNI = 1000        # max number of instances
CNT_MBS = 10485760    # max byte size

# CSV paths (used when mode='csv')
TEMP_CSV  = "test_data/test_data_temp.csv"
HUMID_CSV = "test_data/test_data_humid.csv"

# Random data profiles (used when mode='random')
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
