"""NeuroWalk AR - Phase 0: first EEG recording with the Emotiv EPOC X.

Connects to the Emotiv Cortex API, records 60 s eyes open then 60 s eyes
closed, writes one CSV per data stream and checks the Berger effect
(occipital alpha power at O1/O2 should rise when the eyes are closed).

Usage (see README.md):
    py phase0_record.py                  # real recording, headset on
    py phase0_record.py --mock           # offline test with synthetic data
    py phase0_record.py --analyze FILE   # re-run the alpha check on a pow CSV

Credentials come from the environment variables EMOTIV_CLIENT_ID and
EMOTIV_CLIENT_SECRET, or from cortex_credentials.json next to this script.
They are only ever sent to the local Cortex service and are never printed.
"""

import argparse
import csv
import json
import math
import os
import queue
import random
import ssl
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
CORTEX_URL = "wss://localhost:6868"
CREDENTIALS_FILE = HERE / "cortex_credentials.json"
STREAMS = ["pow", "eq", "mot", "eeg"]  # eeg (raw) usually needs a paid licence
SETTLE_SECONDS = 5.0  # first seconds of each phase are left out of the analysis


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------

def load_credentials():
    client_id = os.environ.get("EMOTIV_CLIENT_ID")
    client_secret = os.environ.get("EMOTIV_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret
    if CREDENTIALS_FILE.exists():
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        client_id = data.get("client_id", "")
        client_secret = data.get("client_secret", "")
        if client_id and client_secret and "PASTE" not in client_id + client_secret:
            return client_id, client_secret
    sys.exit(
        "No Cortex credentials found.\n"
        f"Copy cortex_credentials.example.json to {CREDENTIALS_FILE.name} and paste\n"
        "your Client ID and Client Secret into it (see README.md, step 'Cortex App'),\n"
        "or set EMOTIV_CLIENT_ID and EMOTIV_CLIENT_SECRET."
    )


# --------------------------------------------------------------------------
# Transports: real websocket, or an in-process mock of the Cortex service
# --------------------------------------------------------------------------

class WebSocketTransport:
    def __init__(self, url):
        import websocket  # websocket-client

        host = urlparse(url).hostname
        if host not in ("localhost", "127.0.0.1"):
            raise ValueError("Certificate checks are only turned off for localhost.")
        # Cortex uses a self-signed certificate on localhost.
        self.ws = websocket.create_connection(
            url, sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        )
        self.ws.settimeout(0.5)
        self._timeout_exc = websocket.WebSocketTimeoutException

    def send(self, text):
        self.ws.send(text)

    def recv(self):
        """Return a message, or None if nothing arrived within the timeout."""
        try:
            return self.ws.recv()
        except self._timeout_exc:
            return None

    def close(self):
        self.ws.close()


class MockCortex:
    """Pretends to be the Cortex service, streaming synthetic data.

    Alpha power at the occipital sensors goes up while the recorder says the
    eyes are closed, so the full pipeline can be tested without a headset.
    Raw EEG is refused, as it is for a free account.
    """

    CHANNELS = ["AF3", "F7", "F3", "FC5", "T7", "P7", "O1",
                "O2", "P8", "T8", "FC6", "F4", "F8", "AF4"]
    BANDS = ["theta", "alpha", "betaL", "betaH", "gamma"]
    RATES = {"pow": 8, "eq": 2, "mot": 32}

    def __init__(self, alpha_effect=2.5, allow_eeg=False, seed=1):
        self.alpha_effect = alpha_effect
        self.allow_eeg = allow_eeg
        self.eyes_closed = False  # set by the recorder
        self.rng = random.Random(seed)
        self.inbox = queue.Queue()
        self.subscribed = []
        self.stop = threading.Event()
        self.thread = None
        self.cols = {
            "pow": [f"{c}/{b}" for c in self.CHANNELS for b in self.BANDS],
            "eq": ["batteryPercent", "overall", "sampleRateQuality"] + self.CHANNELS,
            "mot": ["COUNTER_MEMS", "INTERPOLATED_MEMS", "Q0", "Q1", "Q2", "Q3",
                    "ACCX", "ACCY", "ACCZ", "MAGX", "MAGY", "MAGZ"],
            "eeg": ["COUNTER", "INTERPOLATED"] + self.CHANNELS
                   + ["RAW_CQ", "MARKER_HARDWARE", "MARKERS"],
        }

    def send(self, text):
        req = json.loads(text)
        method, rid = req["method"], req["id"]
        params = req.get("params", {})
        if method == "requestAccess":
            result = {"accessGranted": True, "message": "mock"}
        elif method == "authorize":
            result = {"cortexToken": "mock-token"}
        elif method == "queryHeadsets":
            result = [{"id": "EPOCX-E502101F", "status": "connected",
                       "connectedBy": "dongle"}]
        elif method == "createSession":
            result = {"id": "mock-session", "status": params.get("status")}
        elif method == "subscribe":
            success, failure = [], []
            for name in params["streams"]:
                if name == "eeg" and not self.allow_eeg:
                    failure.append({"streamName": "eeg", "code": -32016,
                                    "message": "(mock) Your license does not "
                                               "allow raw EEG access."})
                else:
                    success.append({"streamName": name, "cols": self.cols[name],
                                    "sid": "mock-session"})
                    self.subscribed.append(name)
            result = {"success": success, "failure": failure}
            if self.thread is None:
                self.thread = threading.Thread(target=self._stream, daemon=True)
                self.thread.start()
        elif method in ("unsubscribe", "updateSession", "controlDevice"):
            result = {"mock": True}
            if method == "unsubscribe":
                self.stop.set()
        else:
            self.inbox.put(json.dumps({"id": rid, "jsonrpc": "2.0", "error": {
                "code": -32601, "message": f"mock: unknown method {method}"}}))
            return
        self.inbox.put(json.dumps({"id": rid, "jsonrpc": "2.0", "result": result}))

    def _sample(self, name, t):
        if name == "pow":
            row = []
            for ch in self.CHANNELS:
                for band in self.BANDS:
                    base = {"theta": 4.0, "alpha": 3.0, "betaL": 1.5,
                            "betaH": 1.0, "gamma": 0.4}[band]
                    if band == "alpha" and ch in ("O1", "O2") and self.eyes_closed:
                        base *= self.alpha_effect
                    row.append(round(base * math.exp(self.rng.gauss(0, 0.3)), 4))
            return row
        if name == "eq":
            return [87, 100, 1] + [4] * len(self.CHANNELS)
        if name == "mot":
            return [int(t * 32) % 128, 0, 1.0, 0.0, 0.0, 0.0,
                    round(self.rng.gauss(0, 0.01), 4), round(self.rng.gauss(0, 0.01), 4),
                    round(1 + self.rng.gauss(0, 0.01), 4), 0.0, 0.0, 0.0]
        counter = int(t * 128) % 128
        return [counter, 0] + [round(4200 + self.rng.gauss(0, 10), 3)
                               for _ in self.CHANNELS] + [0, 0, []]

    def _stream(self):
        next_due = {}
        while not self.stop.is_set():
            now = time.time()
            for name in list(self.subscribed):
                if now >= next_due.setdefault(name, now):
                    self.inbox.put(json.dumps({name: self._sample(name, now),
                                               "sid": "mock-session", "time": now}))
                    next_due[name] += 1.0 / self.RATES.get(name, 128)
            time.sleep(0.005)

    def recv(self):
        try:
            return self.inbox.get(timeout=0.5)
        except queue.Empty:
            return None

    def close(self):
        self.stop.set()


# --------------------------------------------------------------------------
# Cortex JSON-RPC client
# --------------------------------------------------------------------------

class CortexError(Exception):
    def __init__(self, method, error):
        self.code = error.get("code")
        self.message = error.get("message", "")
        super().__init__(f"{method} failed ({self.code}): {self.message}")


class CortexClient:
    def __init__(self, transport, on_data, on_warning):
        self.transport = transport
        self.on_data = on_data
        self.on_warning = on_warning
        self.next_id = 1
        self.pending = {}
        self.lock = threading.Lock()
        self.running = True
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        while self.running:
            try:
                text = self.transport.recv()
            except Exception as exc:  # connection dropped
                if self.running:
                    self.on_warning({"code": "connection", "message": str(exc)})
                break
            if text is None:
                continue
            msg = json.loads(text)
            if "id" in msg and ("result" in msg or "error" in msg):
                with self.lock:
                    slot = self.pending.get(msg["id"])
                if slot is not None:
                    slot["reply"] = msg
                    slot["event"].set()
            elif "warning" in msg:
                self.on_warning(msg["warning"])
            else:
                self.on_data(msg)

    def call(self, method, timeout=15.0, **params):
        with self.lock:
            rid = self.next_id
            self.next_id += 1
            slot = {"event": threading.Event(), "reply": None}
            self.pending[rid] = slot
        self.transport.send(json.dumps(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
        if not slot["event"].wait(timeout):
            raise TimeoutError(f"No reply from Cortex to {method} after {timeout:.0f} s")
        with self.lock:
            del self.pending[rid]
        reply = slot["reply"]
        if "error" in reply:
            raise CortexError(method, reply["error"])
        return reply["result"]

    def close(self):
        self.running = False
        self.transport.close()


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------

def beep(times=1, mock=False):
    if mock:
        return
    try:
        import winsound
        for _ in range(times):
            winsound.Beep(880, 250)
            time.sleep(0.1)
    except Exception:
        print("\a" * times, end="", flush=True)


class Recorder:
    """Labels incoming samples with the current phase and writes CSVs."""

    def __init__(self, out_dir, stamp):
        self.out_dir = out_dir
        self.stamp = stamp
        self.phase = "pre"
        self.phase_start = time.time()
        self.cols = {}
        self.files = {}
        self.writers = {}
        self.counts = {}
        self.latest_eq = None
        self.lock = threading.Lock()

    def path(self, stream):
        return self.out_dir / f"{self.stamp}_{stream}.csv"

    def add_stream(self, name, cols):
        self.cols[name] = cols
        f = open(self.path(name), "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["cortex_time", "host_time", "phase", "phase_elapsed_s"] + cols)
        self.files[name], self.writers[name], self.counts[name] = f, w, 0

    def set_phase(self, phase):
        with self.lock:
            self.phase = phase
            self.phase_start = time.time()

    def on_data(self, msg):
        now = time.time()
        for name in self.cols:
            if name in msg:
                values = [json.dumps(v) if isinstance(v, (list, dict)) else v
                          for v in msg[name]]
                with self.lock:
                    elapsed = round(now - self.phase_start, 3)
                    self.writers[name].writerow(
                        [msg.get("time", ""), round(now, 3), self.phase, elapsed] + values)
                    self.counts[name] += 1
                    if name == "eq":
                        self.latest_eq = dict(zip(self.cols["eq"], msg["eq"]))

    def close(self):
        with self.lock:
            for f in self.files.values():
                f.close()


EQ_WORDS = {0: "none", 1: "bad", 2: "poor", 3: "fair", 4: "good"}


def print_contact_quality(rec):
    eq = rec.latest_eq
    if not eq:
        print("  (no contact-quality data yet)")
        return
    sensors = [c for c in rec.cols["eq"]
               if c not in ("batteryPercent", "overall", "sampleRateQuality")]
    parts = [f"{s}={EQ_WORDS.get(eq[s], eq[s])}" for s in sensors]
    print(f"  Battery {eq.get('batteryPercent')}%  |  overall contact {eq.get('overall')}%")
    print("  " + "  ".join(parts))
    weak = [s for s in sensors if eq[s] is not None and eq[s] < 3]
    if weak:
        print(f"  Re-wet / reseat: {', '.join(weak)}   (O1 and O2 matter most here)")


def run_phase(rec, name, seconds, prompt, mock, mock_server=None):
    print("\n" + "=" * 60)
    print(prompt)
    print("=" * 60)
    if mock_server is not None:
        mock_server.eyes_closed = (name == "eyes_closed")
    rec.set_phase(name)
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            break
        print(f"\r  {name.replace('_', ' ')}: {left:5.1f} s left   ", end="", flush=True)
        time.sleep(min(0.2 if mock else 1.0, left))
    print()


def connect_headset(client, token, mock):
    for attempt in range(30):
        headsets = client.call("queryHeadsets")
        connected = [h for h in headsets if h.get("status") == "connected"]
        if connected:
            return connected[0]
        found = [h for h in headsets if h.get("status") == "discovered"]
        if found:
            print(f"Headset {found[0]['id']} found - asking Cortex to connect it...")
            try:
                client.call("controlDevice", command="connect", headset=found[0]["id"])
            except CortexError as exc:
                print(f"  {exc}")
        elif attempt == 0:
            print("No headset found yet. Switch the EPOC X on and connect it in "
                  "EMOTIV Launcher (USB dongle). Waiting up to 60 s...")
            try:
                client.call("controlDevice", command="refresh")
            except CortexError:
                pass
        time.sleep(0.1 if mock else 2.0)
    sys.exit("No connected headset. Check EMOTIV Launcher, then run the script again.")


def record(args):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = Recorder(out_dir, stamp)

    warnings = []

    def on_warning(w):
        warnings.append(w)
        print(f"\n  [Cortex warning {w.get('code')}] {w.get('message')}")

    mock_server = None
    if args.mock:
        mock_server = MockCortex(alpha_effect=args.mock_alpha_effect)
        transport = mock_server
        client_id, client_secret = "mock-id", "mock-secret"
        print("MOCK MODE - synthetic data, no headset needed.")
    else:
        client_id, client_secret = load_credentials()
        try:
            transport = WebSocketTransport(CORTEX_URL)
        except Exception as exc:
            sys.exit(f"Could not reach Cortex at {CORTEX_URL}: {exc}\n"
                     "Is EMOTIV Launcher running and are you logged in?")

    client = CortexClient(transport, rec.on_data, on_warning)
    session_id = None
    token = None
    summary = {"started": stamp, "mock": args.mock}
    try:
        # 1. requestAccess - the first time, approve the app in EMOTIV Launcher.
        print("Requesting access...")
        for i in range(40):
            res = client.call("requestAccess", clientId=client_id, clientSecret=client_secret)
            if res.get("accessGranted"):
                break
            if i == 0:
                print("  Please approve this app in EMOTIV Launcher (a pop-up should appear).")
            time.sleep(3)
        else:
            sys.exit("Access was not granted in EMOTIV Launcher.")

        # 2. authorize
        token = client.call("authorize", clientId=client_id,
                            clientSecret=client_secret)["cortexToken"]
        print("Authorized.")

        # 3. queryHeadsets
        headset = connect_headset(client, token, args.mock)
        print(f"Headset connected: {headset['id']} "
              f"(via {headset.get('connectedBy', 'unknown')})")
        summary["headset"] = headset["id"]
        summary["connected_by"] = headset.get("connectedBy")

        # 4. createSession
        try:
            session = client.call("createSession", cortexToken=token,
                                  headset=headset["id"], status="active")
        except CortexError as exc:
            print(f"  Active session refused ({exc.message}); trying an open session.")
            session = client.call("createSession", cortexToken=token,
                                  headset=headset["id"], status="open")
        session_id = session["id"]

        # 5. subscribe, one stream at a time so a refusal cannot block the others
        allowed, refused = [], {}
        for name in STREAMS:
            try:
                res = client.call("subscribe", cortexToken=token,
                                  session=session_id, streams=[name])
            except CortexError as exc:
                refused[name] = f"{exc.code}: {exc.message}"
                continue
            for ok in res.get("success", []):
                rec.add_stream(ok["streamName"], ok["cols"])
                allowed.append(ok["streamName"])
            for bad in res.get("failure", []):
                refused[bad["streamName"]] = f"{bad.get('code')}: {bad.get('message')}"

        print("\nStreams your account allows:")
        for name in STREAMS:
            if name in allowed:
                print(f"  {name:4s} YES  ({len(rec.cols[name])} columns)")
            else:
                print(f"  {name:4s} NO   {refused.get(name, '')}")
        summary["streams_allowed"] = allowed
        summary["streams_refused"] = refused
        if "pow" not in allowed:
            sys.exit("Band power (pow) is not available, so the alpha check cannot run.")

        # Contact-quality check before starting
        time.sleep(0.5 if args.mock else 2.0)
        print("\nContact quality right now:")
        if "eq" in allowed:
            print_contact_quality(rec)
        if not args.yes:
            while True:
                ans = input("\nSit still, relax your face and jaw. Press Enter to start "
                            "(r + Enter to refresh contact quality, q to quit): ").strip().lower()
                if ans == "q":
                    return 1
                if ans == "r":
                    print_contact_quality(rec)
                    continue
                break

        # Eyes open -> eyes closed
        beep(1, args.mock)
        run_phase(rec, "eyes_open", args.open_seconds,
                  f"EYES OPEN for {args.open_seconds:.0f} s.\n"
                  "Look softly at one spot in front of you. Blink normally, "
                  "don't talk or clench.", args.mock, mock_server)
        rec.set_phase("transition")
        print("\nNext: EYES CLOSED. Close your eyes after the double beep and keep "
              "them closed until the triple beep.")
        time.sleep(0.2 if args.mock else 4.0)
        beep(2, args.mock)
        run_phase(rec, "eyes_closed", args.closed_seconds,
                  f"EYES CLOSED for {args.closed_seconds:.0f} s. Stay relaxed and awake.",
                  args.mock, mock_server)
        rec.set_phase("post")
        beep(3, args.mock)
        print("\nDone - you can open your eyes.")
        time.sleep(0.3)
    finally:
        if session_id and token:
            try:
                client.call("unsubscribe", cortexToken=token, session=session_id,
                            streams=list(rec.cols), timeout=5)
                client.call("updateSession", cortexToken=token, session=session_id,
                            status="close", timeout=5)
            except Exception:
                pass
        client.close()
        rec.close()

    print("\nSaved:")
    for name in rec.cols:
        print(f"  {rec.path(name)}  ({rec.counts[name]} samples)")
    summary["samples"] = rec.counts
    summary["warnings"] = warnings
    result = analyze(rec.path("pow"), args.settle)
    summary["berger_check"] = result
    summary_path = out_dir / f"{stamp}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  {summary_path}")
    return 0 if result.get("verdict") == "PASS" else 2


# --------------------------------------------------------------------------
# Analysis: Berger effect at O1/O2
# --------------------------------------------------------------------------

def analyze(pow_csv, settle=SETTLE_SECONDS):
    pow_csv = Path(pow_csv)
    with open(pow_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    channels = ["O1/alpha", "O2/alpha"]
    missing = [c for c in channels if rows and c not in rows[0]]
    if not rows or missing:
        print(f"\nCannot analyse {pow_csv.name}: no data or missing columns {missing}")
        return {"verdict": "NO DATA"}

    def mean_for(phase, col):
        vals = []
        for r in rows:
            if r["phase"] == phase and float(r["phase_elapsed_s"]) >= settle:
                try:
                    vals.append(float(r[col]))
                except ValueError:
                    pass  # empty / non-numeric sample
        return (sum(vals) / len(vals), len(vals)) if vals else (float("nan"), 0)

    print("\n" + "=" * 60)
    print(f"Berger check: mean alpha power (first {settle:.0f} s of each phase skipped)")
    print("=" * 60)
    print(f"  {'sensor':8s} {'eyes open':>12s} {'eyes closed':>12s} {'closed/open':>12s}")
    result = {"channels": {}}
    ratios = []
    n_open = n_closed = 0
    for col in channels:
        m_open, n_open = mean_for("eyes_open", col)
        m_closed, n_closed = mean_for("eyes_closed", col)
        ratio = m_closed / m_open if m_open > 0 else float("nan")
        ratios.append(ratio)
        result["channels"][col] = {"eyes_open": m_open, "eyes_closed": m_closed,
                                   "ratio": ratio}
        print(f"  {col.split('/')[0]:8s} {m_open:12.3f} {m_closed:12.3f} {ratio:11.2f}x")
    if n_open == 0 or n_closed == 0:
        print("  Not enough samples in one of the phases.")
        result["verdict"] = "NO DATA"
        return result
    mean_ratio = sum(ratios) / len(ratios)
    result["mean_ratio"] = mean_ratio
    if mean_ratio > 1.0:
        result["verdict"] = "PASS"
        print(f"\n  PASS - alpha is {mean_ratio:.2f}x higher with eyes closed. "
              "Your setup is picking up real brain activity.")
        if mean_ratio < 1.2:
            print("  (The rise is small. Check O1/O2 contact and try again for a "
                  "clearer result; 1.5x or more is common.)")
    else:
        result["verdict"] = "FAIL"
        print(f"\n  FAIL - alpha did not rise with eyes closed (ratio {mean_ratio:.2f}x).\n"
              "  Usually this means poor contact at O1/O2 or the references: part the hair,\n"
              "  re-wet those sensors, get them green, and record again.")
    print(f"  ({n_open} eyes-open and {n_closed} eyes-closed band-power samples used)")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="NeuroWalk AR Phase 0 EEG recording")
    p.add_argument("--mock", action="store_true",
                   help="use synthetic data instead of the Cortex service")
    p.add_argument("--mock-alpha-effect", type=float, default=2.5,
                   help="mock only: alpha multiplier with eyes closed (1.0 = no effect)")
    p.add_argument("--analyze", metavar="POW_CSV",
                   help="only re-run the alpha check on an existing *_pow.csv")
    p.add_argument("--open-seconds", type=float, default=60.0)
    p.add_argument("--closed-seconds", type=float, default=60.0)
    p.add_argument("--out", default=str(HERE / "recordings"),
                   help="folder for the CSV files (default: recordings/)")
    p.add_argument("--settle", type=float, default=SETTLE_SECONDS,
                   help="seconds at the start of each phase left out of the analysis")
    p.add_argument("--yes", action="store_true",
                   help="start without waiting for Enter")
    args = p.parse_args(argv)
    if args.analyze:
        res = analyze(args.analyze, args.settle)
        return 0 if res.get("verdict") == "PASS" else 2
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
