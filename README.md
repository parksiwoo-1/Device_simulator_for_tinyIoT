# Device_simulator_for_tinyIoT


## Overview

This project provides:

- A **device simulator** that sends random temperature and humidity data to the tinyIoT server
- You can freely add any sensors you want.

The simulator follows the **oneM2M standard** and supports both **HTTP** and **MQTT** protocols for data transmission.

## File Structure

- [`simulator.py`](http://simulator.py/) – Device simulator
- `config_sim.py` – Global configuration values
- `test data/test_data_temp.csv` – Temperature CSV data
- `test data/test_data_humid.csv` – Humidity CSV data

## Features

- You can also use simulator.py via a script called coordination.py, which controls tinyIoT and the simulator.
```bash
  https://github.com/parksiwoo-1/Coordination_scrip_for_tinyIoT
```
- **Temperature and humidity simulation**
- **Protocol**: Choose between **HTTP** or **MQTT**
- **Mode**
    - `csv`: Sequentially sends data from a CSV file
    - `random`: Generates random data within the configured range
- **Frequency**: Set the transmission interval in seconds for data sent to tinyIoT
- **Auto registration**: Create oneM2M AE/CNT resources using the `Registration` option

## Environment

- **OS**: Ubuntu 24.04.2 LTS
- **Language**: Python 3.8+
- **IoT**: [tinyIoT](https://github.com/seslabSJU/tinyIoT)
  <img width="90" height="45" alt="image" src="https://github.com/user-attachments/assets/4ae1149b-fd7f-43a2-bb53-f2e742399279" />

- **MQTT Broker**: [Mosquitto](https://mosquitto.org/)

## Installation

### Python Libraries

```bash
pip install requests

```

```bash
pip install paho-mqtt

```

### tinyIoT Setup

- Go to the tinyIoT GitHub repository

```bash
[Clone and build tinyIoT following the README](https://github.com/seslabSJU/tinyIoT)

```

- tinyIoT `config.h` settings
1. Make sure the following settings are correctly configured:

<img width="684" height="241" alt="image" src="https://github.com/user-attachments/assets/705a3ac5-4dec-4bbc-b35a-976ae12d600b" />

1. Uncomment `#define ENABLE_MQTT`.

<img width="641" height="397" alt="image" src="https://github.com/user-attachments/assets/6b856bbc-0dc7-46b9-bcd9-9a606407592f" />

### MQTT Broker (Mosquitto) Setup

- **Mosquitto installation required**
1. Visit the website
    
    [https://mosquitto.org](https://mosquitto.org/)
    
2. Click **Download** on the site
3. For Windows, download the x64 installer:

```bash
mosquitto-2.0.22-install-windows-x64.exe

```

1. Edit `mosquitto.conf`:
- Add `#listener 1883`, `#protocol mqtt`

<img width="2043" height="282" alt="image" src="https://github.com/user-attachments/assets/6c97477f-eb28-4d64-b71a-f249ff1336cb" />

1. Run
    
    Execute in Windows PowerShell using WSL:
    

```bash
sudo systemctl start mosquitto

```

```bash
sudo systemctl status mosquitto

```

<img width="2162" height="632" alt="image" src="https://github.com/user-attachments/assets/bad124a0-6891-43fe-8ed4-8a9bef79c4ea" />

If it shows “active (running)” as in the image above, the broker setup is complete.

## Running the Device Simulator

### Clone the repository

1. On Ubuntu, move to the directory where you will clone:

```bash
cd tinyIoT/simulator   # example path

```

2. Clone

```bash
git clone https://github.com/parksiwoo-1/Coordination_script_and_Device_simulators_for_tinyIoT

```

3. Move to the cloned directory

```bash
cd tinyIoT/script   # example path

```

4. Run

```bash
python3 simulator.py --sensor {sensor} --protocol {http / mqtt} --mode {csv / random} --frequency {seconds} --registration {1 / 0}
```
