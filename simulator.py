"""Single-sensor oneM2M device simulator for HTTP and MQTT transports."""

import argparse
import csv
import json
import os
import random
import string
import sys
import threading
import time
import uuid
from typing import Dict, Optional, Tuple, List

import paho.mqtt.client as mqtt
import requests
import signal

import config_sim as config

HTTP = requests.Session()
HTTP_REQUEST_TIMEOUT = (config.CONNECT_TIMEOUT, config.READ_TIMEOUT)

class Headers:
    """Utility that assembles per-request oneM2M HTTP headers."""

    def __init__(self, content_type: Optional[str] = None, origin: str = "CAdmin", ri: str = "req"):
        """Build oneM2M HTTP headers: start from defaults, set X-M2M-Origin/RI, and add Content-Type (application/json;ty=…) only when a resource type is given."""
        self.headers = dict(config.HTTP_DEFAULT_HEADERS)
        self.headers["X-M2M-Origin"] = origin
        self.headers["X-M2M-RI"] = ri
        if content_type:
            self.headers["Content-Type"] = f"application/json;ty={self.get_content_type(content_type)}"

    @staticmethod
    def get_content_type(content_type: str):
        """Translate logical names into numeric content type codes."""
        return config.HTTP_CONTENT_TYPE_MAP.get(content_type)


def url_ae(ae: str) -> str:
    """Return the absolute URL of an AE resource."""
    return f"{config.BASE_URL_RN}/{ae}"


def url_cnt(ae: str, cnt: str) -> str:
    """Return the absolute URL of a CNT resource under the given AE."""
    return f"{config.BASE_URL_RN}/{ae}/{cnt}"


def _x_rsc(resp) -> Optional[int]:
    """Extract the ``X-M2M-RSC`` response header when available."""
    try:
        v = resp.headers.get("X-M2M-RSC") or resp.headers.get("x-m2m-rsc")
        return int(v) if v is not None else None
    except Exception:
        return None


def _admin_delete_with_verification(paths: List[str]) -> bool:
    """Delete as CAdmin; all targets must succeed — exit on any failure including 404."""
    hdr = Headers(origin="CAdmin").headers
    for p in dict.fromkeys(paths):
        try:
            r = HTTP.delete(p, headers=hdr, timeout=HTTP_REQUEST_TIMEOUT)
            rsc = _x_rsc(r)
            if not (r.status_code in (200, 202, 204) or rsc == 2002):
                print(f"[ERROR] DELETE {p} -> {r.status_code} rsc={rsc} body={getattr(r, 'text', '')}")
                sys.exit(1)
        except Exception as exc:
            print(f"[ERROR] DELETE {p} failed: {exc}")
            sys.exit(1)
    return True


def http_create_ae(ae_rn: str, api: str) -> Tuple[bool, Optional[str]]:
    """Create AE and return AEI; on RN conflict delete existing and retry once; fallback to Origin if AEI missing."""
    unique_origin = f"{ae_rn}-{uuid.uuid4().hex[:8]}"

    def _try_create(origin_for_create: str):
        try:
            r = HTTP.post(
                config.BASE_URL_RN,
                headers=Headers("ae", origin=origin_for_create).headers,
                json={"m2m:ae": {"rn": ae_rn, "api": api, "rr": True}},
                timeout=HTTP_REQUEST_TIMEOUT,
            )
            rsc_hdr = _x_rsc(r)
            if r.status_code in (200, 201) or rsc_hdr == 2001:
                try:
                    js = r.json()
                    aei = js.get("m2m:ae", {}).get("aei")
                except Exception:
                    aei = None
                if not aei:
                    aei = origin_for_create
                return True, aei, r
            return False, None, r
        except Exception as e:
            return False, None, e

    ok, aei, r = _try_create(unique_origin)
    if ok:
        return True, aei

    if isinstance(r, requests.Response):
        rsc = _x_rsc(r)
        body_text = r.text if hasattr(r, "text") else ""
        if r.status_code in (409,) or rsc == 4105 or "already exists" in (body_text or "").lower():
            candidates = [url_ae(ae_rn)]
            print(f"[HTTP] AE RN duplicate -> DELETE {candidates} (as CAdmin) and retry")
            if not _admin_delete_with_verification(candidates):
                return False, None
            ok2, aei2, r2 = _try_create(unique_origin)
            if ok2:
                return True, aei2
            if isinstance(r2, requests.Response):
                print(f"[ERROR] AE re-create HTTP -> {r2.status_code} {r2.text}")
            else:
                print(f"[ERROR] AE re-create HTTP failed: {r2}")
            return False, None
        else:
            print(f"[ERROR] AE create HTTP -> {r.status_code} {body_text}")
            return False, None
    else:
        print(f"[ERROR] AE create HTTP failed: {r}")
        return False, None


def http_create_cnt(ae_rn: str, cnt_rn: str, origin_aei: str) -> bool:
    """Create CNT under AE using origin AEI; on RN conflict delete existing and retry once; return True on success else False."""
    def _try_create():
        try:
            r = HTTP.post(
                url_ae(ae_rn),
                headers=Headers("cnt", origin=origin_aei).headers,
                json={"m2m:cnt": {"rn": cnt_rn, "mni": config.CNT_MNI, "mbs": config.CNT_MBS}},
                timeout=HTTP_REQUEST_TIMEOUT,
            )
            if r.status_code in (200, 201):
                return True, r
            return False, r
        except Exception as e:
            return False, e

    ok, r = _try_create()
    if ok:
        return True

    if isinstance(r, requests.Response):
        rsc = _x_rsc(r)
        body_text = r.text if hasattr(r, "text") else ""
        if r.status_code in (409,) or rsc == 4105 or "already exists" in (body_text or "").lower():
            candidates = [url_cnt(ae_rn, cnt_rn)]
            print(f"[HTTP] CNT RN duplicate -> DELETE {candidates} (as CAdmin) and retry")
            if not _admin_delete_with_verification(candidates):
                return False
            ok2, r2 = _try_create()
            if ok2:
                return True
            if isinstance(r2, requests.Response):
                print(f"[ERROR] CNT re-create HTTP -> {r2.status_code} {r2.text}")
            else:
                print(f"[ERROR] CNT re-create HTTP failed: {r2}")
            return False
        else:
            print(f"[ERROR] CNT create HTTP -> {r.status_code} {body_text}")
            return False
    else:
        print(f"[ERROR] CNT create HTTP failed: {r}")
        return False


def get_latest_con(ae_rn, cnt_rn) -> Optional[str]:
    """Fetch the latest ``cin.con`` value for the container if present."""
    la = f"{url_cnt(ae_rn, cnt_rn)}/la"
    try:
        r = HTTP.get(la, headers=config.HTTP_GET_HEADERS, timeout=HTTP_REQUEST_TIMEOUT)
        if r.status_code == 200:
            js = r.json()
            return js.get("m2m:cin", {}).get("con")
    except Exception:
        pass
    return None


def _healthcheck_once() -> bool:
     """Try exactly once to contact the tinyIoT CSE over HTTP"""
     url = getattr(config, "CSE_URL", None) or getattr(config, "BASE_URL_RN", None)
     if not url:
         return True
     headers = getattr(
         config,
         "HTTP_GET_HEADERS",
         {"X-M2M-Origin": "CAdmin", "X-M2M-RVI": "3", "X-M2M-RI": "healthcheck"},
     )
     ct = getattr(config, "CONNECT_TIMEOUT", 1)
     rt = getattr(config, "READ_TIMEOUT", 1)
     try:
         r = HTTP.get(url, headers=headers, timeout=(ct, rt))
         ok = (r.status_code == 200)
         if ok:
             print(f"[SIM] tinyIoT server is responsive at {url}.")
         else:
             print(f"[SIM][ERROR] tinyIoT healthcheck failed: HTTP {r.status_code} {url}")
         return ok
     except requests.exceptions.RequestException as e:
         print(f"[SIM][ERROR] tinyIoT healthcheck error at {url}: {e}")
         return False


def send_cin_http(ae_rn: str, cnt_rn: str, value, origin_aei: str) -> bool:
    """POST CIN to AE/CNT using origin AEI; success on 200/201, on timeout verify via /la and accept if stored, else False."""
    hdr = Headers(content_type="cin", origin=origin_aei).headers
    body = {"m2m:cin": {"con": value}}
    u = url_cnt(ae_rn, cnt_rn)
    try:
        r = HTTP.post(u, headers=hdr, json=body, timeout=HTTP_REQUEST_TIMEOUT)
        if r.status_code in (200, 201):
            return True
        try:
            text = r.json()
        except Exception:
            text = r.text
        print(f"[ERROR] POST {u} -> {r.status_code} {text}")
        return False
    except requests.exceptions.ReadTimeout:
        latest = get_latest_con(ae_rn, cnt_rn)
        if latest == str(value):
            print("[WARN] POST timed out but verified via /la (stored).")
            return True
        print("[WARN] POST timed out and not verified; will retry.")
        return False
    except Exception as e:
        print(f"[ERROR] POST {u} failed: {e}")
        return False
    

class MqttOneM2MClient:
    """Paho MQTT client specialized for oneM2M request/response messaging."""

    def __init__(self, broker, port, origin, cse_csi, cse_rn="TinyIoT"):
        self.broker = broker
        self.port = int(port)
        self.origin = origin
        self.cse_csi = cse_csi
        self.cse_rn = cse_rn
        self.response_received = threading.Event()
        self.last_response = None

        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.req_topic = f"/oneM2M/req/{self.origin}/{self.cse_csi}/json"
        self.resp_topic = f"/oneM2M/resp/{self.origin}/{self.cse_csi}/json"
        
    def _update_topics(self):
        self.req_topic = f"/oneM2M/req/{self.origin}/{self.cse_csi}/json"
        self.resp_topic = f"/oneM2M/resp/{self.origin}/{self.cse_csi}/json"

    def set_origin(self, new_origin: str):
        """Switch origin (fr) at runtime and resubscribe to new response topic."""
        try:
            # Unsubscribe previous response topic if connected
            self.client.unsubscribe(self.resp_topic)
        except Exception:
            pass
        self.origin = new_origin
        self._update_topics()
        try:
            self.client.subscribe(self.resp_topic, qos=0)
            print(f"[MQTT] SWITCH ORIGIN -> {self.origin}; SUB {self.resp_topic}")
        except Exception as e:
            print(f"[ERROR] Failed to resubscribe with new origin: {e}")

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        code = getattr(reason_code, "value", reason_code)
        code = 0 if code is None else code
        print("[MQTT] Connection successful." if code == 0 else f"[MQTT] Connection failed: rc={code}")

    def on_disconnect(self, client, userdata, reason_code, properties=None):
        code = getattr(reason_code, "value", reason_code)
        code = 0 if code is None else code
        print(f"[MQTT] Disconnected rc={code}")

    def on_message(self, client, userdata, msg):
        try:
            payload_txt = msg.payload.decode()
            self.last_response = json.loads(payload_txt)
            self.response_received.set()
            print(f"\n[MQTT][RECV] {payload_txt}\n\n", end="\n\n", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to parse MQTT response: {e}")

    def connect(self) -> bool:
        """Connect to the broker, start the loop, and subscribe to the response topic."""
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
            try:
                self.client.unsubscribe(self.resp_topic)
            except Exception:
                pass
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        print("[MQTT] Disconnected.")

    def _send_request(self, body, ok_rsc=(2000, 2001, 2004)):
        """Send a oneM2M request and block until the matching response arrives."""
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
        print(f"[MQTT][SEND] {json.dumps(message, ensure_ascii=False)}")
        self.response_received.clear()
        self.client.publish(self.req_topic, json.dumps(message))
        if self.response_received.wait(timeout=5):
            response = self.last_response or {}
            try:
                rsc = int(response.get("rsc"))
            except Exception:
                rsc = 0
            if rsc in ok_rsc:
                return "ok", response
            return "error", response
        print("[ERROR] No MQTT response within timeout.")
        return "timeout", None
    
    def create_ae(self, ae_name: str, api: str) -> Tuple[bool, Optional[str]]:
        """Create AE over MQTT; on 4105 (RN duplicate) delete via HTTP as CAdmin and retry once; return (ok, aei)."""
        req = {
            "to": self.cse_rn,
            "op": 1,
            "ty": 2,
            "pc": {"m2m:ae": {"rn": ae_name, "api": api, "rr": True}}
        }
        status, resp = self._send_request(req, ok_rsc=(2001,))
        if status == "ok":
            aei = None
            try:
                aei = (resp or {}).get("pc", {}).get("m2m:ae", {}).get("aei")
            except Exception:
                aei = None
            return True, (aei or self.origin)
        if status == "error":
            try:
                rsc = int((resp or {}).get("rsc", 0))
            except Exception:
                rsc = 0
            if rsc == 4105:
                candidates = [url_ae(ae_name)]
                print(f"[MQTT] AE RN duplicate -> DELETE {candidates} (as CAdmin) and retry")
                if not _admin_delete_with_verification(candidates):
                    return False, None
                status2, resp2 = self._send_request(req, ok_rsc=(2001,))
                if status2 == "ok":
                    aei2 = None
                    try:
                        aei2 = (resp2 or {}).get("pc", {}).get("m2m:ae", {}).get("aei")
                    except Exception:
                        aei2 = None
                    return True, (aei2 or self.origin)
                return False, None
            print(f"[ERROR] MQTT AE create failed rsc={rsc} msg={resp}")
            return False, None
        print("[ERROR] MQTT AE create timed out (no response).")
        return False, None

    def create_cnt(self, ae_name: str, cnt_name: str) -> bool:
        """Create CNT under AE over MQTT; on 4105 delete via HTTP as CAdmin and retry once."""
        req = {
            "to": f"{self.cse_rn}/{ae_name}",
            "op": 1,
            "ty": 3,
            "pc": {"m2m:cnt": {"rn": cnt_name}}
        }
        status, resp = self._send_request(req, ok_rsc=(2001,))
        if status == "ok":
            return True
        if status == "error":
            try:
                rsc = int((resp or {}).get("rsc", 0))
            except Exception:
                rsc = 0
            if rsc == 4105:
                candidates = [url_cnt(ae_name, cnt_name)]
                print(f"[MQTT] CNT RN duplicate -> DELETE {candidates} (as CAdmin) and retry")
                if not _admin_delete_with_verification(candidates):
                    return False
                status2, _ = self._send_request(req, ok_rsc=(2001,))
                return status2 == "ok"
            print(f"[ERROR] MQTT CNT create failed rsc={rsc} msg={resp}")
            return False
        print("[ERROR] MQTT CNT create timed out (no response).")
        return False

    def send_cin(self, ae_name: str, cnt_name: str, value):
        """Publish a CIN using the MQTT binding (one retry on failure)."""
        attempts = 0
        status, resp = "", None
        while attempts < 2:
            attempts += 1
            status, resp = self._send_request({
                "to": f"{self.cse_rn}/{ae_name}/{cnt_name}",
                "op": 1,
                "ty": 4,
                "pc": {"m2m:cin": {"con": value}}
            }, ok_rsc=(2001,))
            if status == "ok":
                return True
            if attempts < 2:
                print("[MQTT] CIN send failed; retrying once...")

        if status == "timeout":
            print("[ERROR] No MQTT response within timeout during CIN send (after retry).")
        elif resp:
            print(f"[ERROR] CIN send failed after retry rsc={resp.get('rsc')} msg={resp}")
        else:
            print("[ERROR] CIN send failed after retry (unknown response).")
        return False


def ensure_registration_http(ae: str, cnt: str, api: str, do_register: bool) -> Tuple[bool, Optional[str]]:
    """If do_register is True, create AE then CNT using AEI and return (True, AEI); on failure return (False, None); if skipped return (True, None)."""
    if not do_register:
        return True, None
    print(f"[HTTP] AE create -> {ae}")
    ok, aei = http_create_ae(ae, api)
    if not ok or not aei:
        return False, None
    print(f"[HTTP] CNT create -> {ae}/{cnt}")
    if not http_create_cnt(ae, cnt, origin_aei=aei):
        return False, None
    return True, aei


def build_sensor_meta(name: str) -> Dict:
    """Return the aggregated metadata describing how a sensor should operate."""
    sensor_key = name.lower()
    upper = sensor_key.upper()
    resources = getattr(config, "SENSOR_RESOURCES", {})
    meta = dict(resources.get(sensor_key, {}))

    if not meta:
        template = getattr(config, "GENERIC_SENSOR_TEMPLATE", {})
        if template:
            meta = {k: v.format(sensor=sensor_key) for k, v in template.items()}
        else:
            meta = {
                "ae": f"C{sensor_key}Sensor",
                "cnt": sensor_key,
                "api": f"N.{sensor_key}",
                "origin": f"C{sensor_key}Sensor",
            }

    meta.setdefault("ae", f"C{sensor_key}Sensor")
    meta.setdefault("cnt", sensor_key)
    meta.setdefault("api", f"N.{sensor_key}")
    meta.setdefault("origin", meta.get("ae") or f"C{sensor_key}Sensor")

    meta["profile"] = meta.get(
        "profile",
        getattr(config, f"{upper}_PROFILE", {"data_type": "float", "min": 0, "max": 100})
    )
    meta["csv"] = meta.get("csv", getattr(config, f"{upper}_CSV", None))
    return meta


class SensorWorker:
    """Lifecycle manager that emits sensor readings over HTTP or MQTT."""

    def __init__(self, sensor_name: str, protocol: str, mode: str,
                 period_sec: float, registration: int):
        self.meta = build_sensor_meta(sensor_name)
        self.sensor_name = sensor_name
        self.protocol = protocol
        self.mode = mode
        self.period_sec = float(period_sec)
        self.registration = registration
        self.stop_flag = threading.Event()
        self.csv_data, self.csv_index, self.err = [], 0, 0
        self.mqtt = None
        self.aei: Optional[str] = None
        self._signals_installed = False
        
    def _install_signal_handlers_once(self):
        if self._signals_installed:
            return
        self._signals_installed = True

        def _handler(signum, frame):
            self.stop()
            print(f"\n[SIM] Caught signal {signum}. Stopping...", flush=True)

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, _handler)
            except Exception:
                pass

    def setup(self):
        """Resolve metadata, perform optional registration, and stage data sources."""
        self._install_signal_handlers_once()
        if self.protocol == "http":
            ok, aei = ensure_registration_http(
                self.meta["ae"], self.meta["cnt"], self.meta["api"], do_register=(self.registration == 1)
            )
            if self.registration == 1 and not ok:
                print("[ERROR] HTTP registration failed.")
                raise SystemExit(1)
            self.aei = aei or f"{self.meta['ae']}-{uuid.uuid4().hex[:8]}"
        else:
            tmp_origin = f"{self.meta['ae']}-{uuid.uuid4().hex[:8]}"
            self.mqtt = MqttOneM2MClient(
                config.MQTT_HOST, config.MQTT_PORT, tmp_origin, config.CSE_NAME, config.CSE_RN
            )
            if not self.mqtt.connect():
                print("[ERROR] MQTT broker connect failed. terminate.")
                raise SystemExit(1)
            
            if self.registration == 1:
                print(f"[MQTT] AE create -> {self.meta['ae']}")
                ok, aei = self.mqtt.create_ae(self.meta["ae"], self.meta["api"])
                if not ok or not aei:
                    print("[ERROR] MQTT AE create failed.")
                    raise SystemExit(1)
                self.mqtt.set_origin(aei)
                print(f"[MQTT] CNT create -> {self.meta['ae']}/{self.meta['cnt']}")
                if not self.mqtt.create_cnt(self.meta["ae"], self.meta["cnt"]):
                    print("[ERROR] MQTT CNT create failed.")
                    raise SystemExit(1)
            else:
                pass

        if self.mode == "csv":
            path = self.meta.get("csv")
            if not path:
                print(f"[{self.sensor_name.upper()}][ERROR] CSV path not configured in config for '{self.sensor_name}'.")
                raise SystemExit(1)
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames or "value" not in [h.strip() for h in reader.fieldnames]:
                        print(f"[{self.sensor_name.upper()}][ERROR] CSV header must include 'value' column.")
                        raise SystemExit(1)
                    self.csv_data = []
                    for row in reader:
                        try:
                            v = str(row.get("value", "")).strip()
                        except Exception:
                            v = ""
                        if v != "":
                            self.csv_data.append(v)
            except Exception as e:
                print(f"[{self.sensor_name.upper()}][ERROR] CSV open/parse failed: {e}")
                raise SystemExit(1)
            if not self.csv_data:
                print(f"[{self.sensor_name.upper()}][ERROR] CSV has no 'value' data.")
                raise SystemExit(1)

    def stop(self):
        """Signal the worker loop to stop after the current iteration."""
        self.stop_flag.set()

    def _next_value(self) -> str:
        """Return the next payload to send based on the configured mode."""
        if self.mode == "csv":
            v = self.csv_data[self.csv_index]
            self.csv_index += 1
            return v
        profile = self.meta["profile"]
        dt = profile.get("data_type", "float")
        if dt == "int":
            return str(random.randint(int(profile.get("min", 0)), int(profile.get("max", 100))))
        if dt == "float":
            return f"{random.uniform(float(profile.get("min", 0.0)), float(profile.get("max", 100.0))):.2f}"
        if dt == "string":
            length = int(profile.get("length", 8))
            return "".join(random.choices(string.ascii_letters + string.digits, k=length))
        return "0"

    def run(self):
        """Main worker loop that enforces the send cadence; on any send failure, print error and exit."""
        print(f"[{self.sensor_name.upper()}] run (protocol={self.protocol}, mode={self.mode}, period={self.period_sec}s)")
        next_send = time.time() + self.period_sec
        try:
            while not self.stop_flag.is_set():
                remaining = next_send - time.time()
                while remaining > 0 and not self.stop_flag.is_set():
                    sleep_slice = remaining if remaining < 0.1 else 0.1
                    time.sleep(sleep_slice)
                    remaining = next_send - time.time()
                if self.stop_flag.is_set():
                    break

                if self.mode == "csv" and self.csv_index >= len(self.csv_data):
                    print(f"[{self.sensor_name.upper()}] CSV done. stop.")
                    break

                value = self._next_value()

                if self.protocol == "http":
                    ok = send_cin_http(self.meta["ae"], self.meta["cnt"], value, origin_aei=self.aei)
                else:
                    ok = self.mqtt.send_cin(self.meta["ae"], self.meta["cnt"], value)

                if not ok:
                    print(f"[{self.sensor_name.upper()}][ERROR] send failed: {value}. exiting.")
                    raise SystemExit(1)

                print(f"[{self.sensor_name.upper()}] Sent value: {value}\n")

                if self.mode == "csv" and self.csv_index >= len(self.csv_data):
                    print(f"[{self.sensor_name.upper()}] CSV done. stop.")
                    break

                next_send += self.period_sec
        finally:
            if self.mqtt:
                try:
                    self.mqtt.disconnect()
                except Exception:
                    pass
            print(f"[{self.sensor_name.upper()}] stopped.")
            
            try:
                HTTP.close()
            except Exception:
                pass


def parse_args(argv):
    """Parse CLI options for the simulator entry point."""
    p = argparse.ArgumentParser(description="Single-sensor oneM2M simulator (HTTP/MQTT).")
    p.add_argument("--sensor", required=True)
    p.add_argument("--protocol", choices=["http", "mqtt"], required=True)
    p.add_argument("--mode", choices=["csv", "random"], required=True)
    p.add_argument("--frequency", type=float, required=True)
    p.add_argument("--registration", type=int, choices=[0, 1], required=True)
    return p.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    if os.getenv("SKIP_HEALTHCHECK", "0") != "1":
        if not _healthcheck_once():
            sys.exit(1)
    worker = SensorWorker(
        sensor_name=args.sensor,
        protocol=args.protocol,
        mode=args.mode,
        period_sec=args.frequency,
        registration=args.registration,
    )
    worker._install_signal_handlers_once()
    worker.setup()
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()
        print("\n[SIM] Interrupted.")


if __name__ == "__main__":
    main()
