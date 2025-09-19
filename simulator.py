import argparse, csv, json, random, requests, select, socket, string, sys, time, threading, uuid 
from typing import Dict, List, Tuple
import paho.mqtt.client as mqtt
import config_sim as config

HTTP = requests.Session()

class Headers:
    def __init__(self, content_type=None, origin='CAdmin', ri='req'):
        self.headers = {
            'Accept': 'application/json',
            'X-M2M-Origin': origin,
            'X-M2M-RVI': '2a',
            'X-M2M-RI': ri,
            'Content-Type': 'application/json'
        }
        if content_type:
            self.headers['Content-Type'] = f'application/json;ty={self.get_content_type(content_type)}'
    @staticmethod
    
    def get_content_type(content_type):
        return {'ae': 2, 'cnt': 3, 'cin': 4}.get(content_type)

GET_HEADERS = {
    'Accept': 'application/json',
    'X-M2M-Origin': 'CAdmin',
    'X-M2M-RVI': '2a',
    'X-M2M-RI': 'check'
}

BASE_URL_RN = f"http://{config.HTTP_HOST}:{config.HTTP_PORT}/{config.CSE_RN}"
def url_ae(ae):       return f"{BASE_URL_RN}/{ae}"
def url_cnt(ae, cnt): return f"{BASE_URL_RN}/{ae}/{cnt}"

SENSORS: Dict[str, Dict] = {
    "temp": {
        "ae": "CtempSensor",
        "cnt": "temperature",
        "profile": getattr(config, 'TEMP_PROFILE', {"data_type":"float","min":20,"max":35}),
        "csv": getattr(config, 'TEMP_CSV', None),
        "api": "N.temp",
        "origin": "CtempSensor",
    },
    "humid": {
        "ae": "ChumidSensor",
        "cnt": "humidity",
        "profile": getattr(config, 'HUMID_PROFILE', {"data_type":"float","min":50,"max":90}),
        "csv": getattr(config, 'HUMID_CSV', None),
        "api": "N.humid",
        "origin": "ChumidSensor",
    },
}

def now_ns() -> int: return time.monotonic_ns()

def wait_until_ns(target_ns: int):
    SPIN_NS = 500_000
    while True:
        rem = target_ns - now_ns()
        if rem <= 0: return
        if rem > SPIN_NS:
            select.select([], [], [], rem / 1e9)
        else:
            while now_ns() < target_ns: pass
            return

class Alternator:
    def __init__(self, order: List[str]):
        self.order = order[:]
        self.idx = 0
        self.cond = threading.Condition()
        self.started = False
    
    def start(self):
        with self.cond:
            self.started = True
            self.cond.notify_all()
    
    def wait_turn(self, name: str):
        with self.cond:
            while not self.started:
                self.cond.wait()
            while self.order[self.idx] != name:
                self.cond.wait()
    
    def done(self):
        with self.cond:
            self.idx = (self.idx + 1) % len(self.order)
            self.cond.notify_all()

def check_http_reachable():
    try:
        with socket.create_connection((config.HTTP_HOST, int(config.HTTP_PORT)), timeout=config.CONNECT_TIMEOUT):
            return True
    except Exception:
        return False

def request_post(url, headers, body, kind=""):
    try:
        r = HTTP.post(url, headers=headers, json=body, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT))
        if r.status_code in (200, 201):
            return True
        x_rsc = str(r.headers.get('X-M2M-RSC', r.headers.get('x-m2m-rsc', ''))).strip()
        if r.status_code == 409 or x_rsc == '4105':
            print(f"[INFO] POST {kind} {url} -> already exists (OK)")
            return True
        try:
            text = r.json()
        except Exception:
            text = r.text
        if any(k in str(text).lower() for k in ("duplicat","already exist","exists")):
            print(f"[INFO] POST {kind} {url} -> duplicate message (OK)")
            return True
        print(f"[ERROR] POST {kind} {url} -> {r.status_code} {text}")
        return False
    except requests.exceptions.ReadTimeout as e:
        print(f"[WARN] POST timeout on {url}: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] POST {url} failed: {e}")
        return False

def get_latest_con(ae, cnt):
    la = f"{url_cnt(ae, cnt)}/la"
    try:
        r = HTTP.get(la, headers=GET_HEADERS, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT))
        if r.status_code == 200:
            js = r.json()
            return js.get('m2m:cin', {}).get('con')
    except Exception:
        pass
    return None

def send_cin_http(ae, cnt, value):
    hdr = Headers(content_type='cin', origin=ae).headers
    body = {"m2m:cin": {"con": value}}
    u = url_cnt(ae, cnt)
    try:
        r = HTTP.post(u, headers=hdr, json=body, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT))
        if r.status_code in (200, 201):
            return True
        try:
            text = r.json()
        except Exception:
            text = r.text
        print(f"[ERROR] POST {u} -> {r.status_code} {text}")
        return False
    except requests.exceptions.ReadTimeout:
        latest = get_latest_con(ae, cnt)
        if latest == str(value):
            print("[WARN] POST timed out but verified via /la (stored).")
            return True
        print("[WARN] POST timed out and not verified; will retry.")
        return False
    except Exception as e:
        print(f"[ERROR] POST {u} failed: {e}")
        return False

def generate_random_value_from_profile(profile):
    dt = profile['data_type']
    if dt == 'int':
        return str(random.randint(int(profile['min']), int(profile['max'])))
    if dt == 'float':
        return f"{random.uniform(float(profile['min']), float(profile['max'])):.2f}"
    if dt == 'string':
        length = int(profile.get('length') or 8)
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    return "0"

def ensure_registration_http_postonly(ae, cnt, api) -> bool:
    ok1 = request_post(BASE_URL_RN, Headers('ae', origin=ae).headers,
                       {"m2m:ae": {"rn": ae, "api": api, "rr": True}}, "ae")
    if not ok1: return False
    ok2 = request_post(url_ae(ae), Headers('cnt', origin=ae).headers,
                       {"m2m:cnt": {"rn": cnt, "mni": config.CNT_MNI, "mbs": config.CNT_MBS}}, "cnt")
    return ok2

class MqttOneM2MClient:
    def __init__(self, broker, port, origin, cse_csi, cse_rn="TinyIoT"):
        self.broker = broker
        self.port = int(port)
        self.origin = origin
        self.cse_csi = cse_csi
        self.cse_rn = cse_rn
        self.response_received = threading.Event()
        self.last_response = None
        print(f"[MQTT] Using module file: {__file__}")
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.req_topic = f"/oneM2M/req/{self.origin}/{self.cse_csi}/json"
        self.resp_topic = f"/oneM2M/resp/{self.origin}/{self.cse_csi}/json"
    
    def on_connect(self, client, userdata, flags, rc):
        print("[MQTT] Connection successful." if rc == 0 else f"[MQTT] Connection failed: rc={rc}")
    
    def on_disconnect(self, client, userdata, rc):
        print(f"[MQTT] Disconnected rc={rc}")
    
    def on_message(self, client, userdata, msg):
        try:
            print(f"[MQTT] [RECV] Topic: {msg.topic}")
            payload_txt = msg.payload.decode()
            print(f"[MQTT] [RECV] Payload: {payload_txt}")
            self.last_response = json.loads(payload_txt)
            self.response_received.set()
        except Exception as e:
            print(f"[ERROR] Failed to parse MQTT response: {e}")
    
    def connect(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            self.client.subscribe(self.resp_topic, qos=0)
            print(f"[MQTT] SUB {self.resp_topic}")
            print(f"[MQTT] Connected to broker {self.broker}:{self.port}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        try:
            self.client.loop_stop()
        finally:
            self.client.disconnect()
        print("[MQTT] Disconnected.")
    
    def _send_request(self, body, ok_rsc=(2000, 2001, 2004)):
        request_id = str(uuid.uuid4())
        message = {
            "fr": self.origin,
            "to": body["to"],
            "op": body["op"],
            "rqi": request_id,
            "ty": body.get("ty"),
            "pc": body.get("pc", {}),
            "rvi": "3"
        }
        req_topic_with_origin = f"/oneM2M/req/{self.origin}/{self.cse_csi}/json"
        print(f"[MQTT] [SEND] Topic: {req_topic_with_origin}")
        print(f"[MQTT] [SEND] Payload:")
        print(json.dumps(message, indent=2, ensure_ascii=False))
        self.response_received.clear()
        self.client.publish(req_topic_with_origin, json.dumps(message))
        if self.response_received.wait(timeout=5):
            try:
                rsc = int(self.last_response.get("rsc", 0))
            except Exception:
                rsc = 0
            return rsc in ok_rsc
        print("[ERROR] No MQTT response received within timeout.")
        return False
    
    def create_ae(self, ae_name):
        ok = self._send_request({
            "to": f"{self.cse_rn}",
            "op": 1,
            "ty": 2,
            "pc": {"m2m:ae": {"rn": ae_name, "api": "N.device", "rr": True}}
        }, ok_rsc=(2001, 4105))
        if not ok and self.last_response:
            print(f"[ERROR] AE create failed rsc={self.last_response.get('rsc')} msg={self.last_response}")
        elif ok and self.last_response and str(self.last_response.get("rsc")) == "4105":
            print("[MQTT] AE already exists. Proceeding.")
        return ok
    
    def create_cnt(self, ae_name, cnt_name):
        ok = self._send_request({
            "to": f"{self.cse_rn}/{ae_name}",
            "op": 1,
            "ty": 3,
            "pc": {"m2m:cnt": {"rn": cnt_name}}
        }, ok_rsc=(2001, 4105))
        if not ok and self.last_response:
            print(f"[ERROR] CNT create failed rsc={self.last_response.get('rsc')} msg={self.last_response}")
        elif ok and self.last_response and str(self.last_response.get("rsc")) == "4105":
            print("[MQTT] CNT already exists. Proceeding.")
        return ok
    
    def send_cin(self, ae_name, cnt_name, value):
        ok = self._send_request({
            "to": f"{self.cse_rn}/{ae_name}/{cnt_name}",
            "op": 1,
            "ty": 4,
            "pc": {"m2m:cin": {"con": value}}
        }, ok_rsc=(2001,))
        if not ok and self.last_response:
            print(f"[ERROR] CIN send failed rsc={self.last_response.get('rsc')} msg={self.last_response}")
        return ok

class SensorWorker(threading.Thread):
    def __init__(self, name, protocol, mode, period_sec, registration, alternator: Alternator):
        super().__init__(daemon=True)
        self.meta = SENSORS[name]
        self.name = name
        self.protocol = protocol
        self.mode = mode
        self.period_ns = int(float(period_sec) * 1e9)
        self.registration = registration
        self.stop_flag = threading.Event()
        self.csv_data, self.csv_index, self.err = [], 0, 0
        self.mqtt = None
        self.alternator = alternator
    
    def setup(self):
        if self.protocol == 'http':
            if not check_http_reachable():
                print(f"[ERROR] Cannot connect HTTP: {config.HTTP_HOST}:{config.HTTP_PORT}"); raise SystemExit(1)
            if self.registration == 1:
                if not ensure_registration_http_postonly(self.meta["ae"], self.meta["cnt"], self.meta["api"]):
                    print("[ERROR] HTTP registration failed."); raise SystemExit(1)
        else:
            self.mqtt = MqttOneM2MClient(config.MQTT_HOST, config.MQTT_PORT, self.meta["origin"], config.CSE_NAME, config.CSE_RN)
            if not self.mqtt.connect(): raise SystemExit(1)
            if self.registration == 1:
                if not self.mqtt.create_ae(self.meta["ae"]):  raise SystemExit(1)
                if not self.mqtt.create_cnt(self.meta["ae"], self.meta["cnt"]): raise SystemExit(1)
        if self.mode == 'csv':
            path = self.meta.get("csv")
            if not path:
                print(f"[{self.name.upper()}][ERROR] CSV path not configured in config for {self.name}.")
                raise SystemExit(1)
            try:
                with open(path, 'r') as f:
                    rows = list(csv.reader(f))
                    self.csv_data = [r[0].strip() for r in rows if r]
            except Exception as e:
                print(f"[{self.name.upper()}][ERROR] CSV open failed: {e}"); raise SystemExit(1)
            if not self.csv_data:
                print(f"[{self.name.upper()}][ERROR] CSV empty."); raise SystemExit(1)
    
    def stop(self): self.stop_flag.set()
    
    def _next_value(self):
        if self.mode == 'csv':
            v = self.csv_data[self.csv_index]; self.csv_index += 1; return v
        return generate_random_value_from_profile(self.meta["profile"])
    
    def run(self):
        print(f"[{self.name.upper()}] run (protocol={self.protocol}, mode={self.mode}, period={self.period_ns/1e9}s)")
        t_next = now_ns() + self.period_ns
        try:
            while not self.stop_flag.is_set():
                wait_until_ns(t_next)
                self.alternator.wait_turn(self.name)
                if self.stop_flag.is_set():
                    try:
                        self.alternator.done()
                    except Exception:
                        pass
                    break
                value = self._next_value()
                ok = send_cin_http(self.meta["ae"], self.meta["cnt"], value) if self.protocol=='http' else self.mqtt.send_cin(self.meta["ae"], self.meta["cnt"], value)
                if ok:
                    print(f"[{self.name.upper()}] Sent: {value}"); self.err = 0
                else:
                    self.err += 1
                    print(f"[{self.name.upper()}][ERROR] send failed: {value} (retry in {config.RETRY_WAIT_SECONDS}s)")
                    wait_until_ns(now_ns() + int(config.RETRY_WAIT_SECONDS * 1e9))
                    if self.err >= config.SEND_ERROR_THRESHOLD:
                        print(f"[{self.name.upper()}][ERROR] repeated failures. stop.")
                        self.alternator.done()
                        break
                if self.mode == 'csv' and self.csv_index >= len(self.csv_data):
                    print(f"[{self.name.upper()}] CSV done. stop.")
                    self.alternator.done()
                    break
                self.alternator.done()
                t_next += self.period_ns
        finally:
            if self.mqtt:
                try: self.mqtt.disconnect()
                except Exception: pass
            print(f"[{self.name.upper()}] stopped.")

def run_all_sensors(sensor_confs: List[Tuple[str, str, str, float, int]]):
    sensor_names = [name for (name, *_rest) in sensor_confs]
    alternator = Alternator(order=sensor_names)
    workers = []
    try:
        for (name, protocol, mode, frequency, registration) in sensor_confs:
            w = SensorWorker(name, protocol, mode, frequency, registration, alternator)
            w.setup()
            workers.append(w)
        alternator.start()
        for w in workers: w.start()
        for w in workers: w.join()
    except KeyboardInterrupt:
        for w in workers:
            w.stop()
        try:
            with alternator.cond:
                alternator.started = True
                alternator.cond.notify_all()
        except Exception:
            pass
        for w in workers:
            try:
                w.join(timeout=2)
            except Exception:
                pass

def _parse_blocks(argv: List[str]) -> List[Tuple[str, str, str, float, int]]:
    i = 0
    blocks = []
    current = None
    def flush_current():
        nonlocal current, blocks
        if current is None: return
        required = ['name', 'protocol', 'mode', 'frequency', 'registration']
        missing = [k for k in required if k not in current]
        if missing:
            raise SystemExit(f"[CLI][ERROR] Missing options for sensor '{current.get('name','?')}'. Required: {', '.join(required)}")
        blocks.append((current['name'], current['protocol'], current['mode'], float(current['frequency']), int(current['registration'])))
        current = None
    while i < len(argv):
        tok = argv[i]
        if tok == '--sensor':
            flush_current()
            if i+1 >= len(argv):
                raise SystemExit("[CLI][ERROR] --sensor requires a value (temp|humid)")
            name = argv[i+1].lower()
            if name not in SENSORS:
                raise SystemExit(f"[CLI][ERROR] Unknown sensor '{name}'. Choose from: {', '.join(SENSORS.keys())}")
            current = {'name': name}
            i += 2
            continue
        if current is not None and tok in ('--protocol','--mode','--frequency','--registration'):
            if i+1 >= len(argv):
                raise SystemExit(f"[CLI][ERROR] {tok} requires a value")
            val = argv[i+1]
            key = tok.lstrip('-')
            current[key] = val
            i += 2
            continue
        i += 1
    flush_current()
    return blocks

def parse_args(argv):
    if '--sensor' in argv:
        blocks = _parse_blocks(argv)
        if not blocks:
            raise SystemExit("[CLI][ERROR] No valid sensor blocks parsed after --sensor.")
        return {'mode': 'per-sim', 'blocks': blocks}
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', choices=['http','mqtt'], required=True)
    p.add_argument('--mode', choices=['csv','random'], required=True)
    p.add_argument('--frequency', type=float, required=True)
    p.add_argument('--registration', type=int, choices=[0,1], required=True)
    args = p.parse_args(argv)
    blocks = []
    for name in SENSORS.keys():
        blocks.append((name, args.protocol, args.mode, float(args.frequency), int(args.registration)))
    return {'mode': 'unified', 'blocks': blocks}

def main():
    parsed = parse_args(sys.argv[1:])
    run_all_sensors(parsed['blocks'])

if __name__ == '__main__':
    main()
