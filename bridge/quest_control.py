"""NeuroWalk AR - control the Quest app from the PC over Wi-Fi (UDP).

The Quest app shows its address on the in-headset panel ("Quest IP ...:9050").

    py quest_control.py --quest 192.168.1.50 ping
    py quest_control.py --quest 192.168.1.50 start
    py quest_control.py --quest 192.168.1.50 level 5
    py quest_control.py --quest 192.168.1.50 mode fixed        # fixed | staircase | external
    py quest_control.py --quest 192.168.1.50 marker "condition A"
    py quest_control.py --quest 192.168.1.50 pause
    py quest_control.py --quest 192.168.1.50 recenter
    py quest_control.py --quest 192.168.1.50 watch             # print live status/trials

Later the EEG bridge will send the same `set_level` messages automatically.
"""

import argparse
import json
import socket
import sys
import time

PORT = 9050


def build_message(command, value):
    if command == "level":
        return {"cmd": "set_level", "level": int(value)}
    if command == "mode":
        return {"cmd": "set_mode", "mode": value}
    if command == "marker":
        return {"cmd": "marker", "label": value or ""}
    if command == "watch":
        return {"cmd": "ping"}
    return {"cmd": command}


def describe(msg):
    if msg.get("type") == "trial":
        rt = f"{msg['rt_ms']:.0f} ms" if msg.get("rt_ms", -1) >= 0 else ""
        return f"trial {msg['trial']:4d}  {msg['outcome']:<18s} {rt:>8s}  level {msg['level']}"
    if msg.get("type") == "status":
        extra = f"  PAUSED: {msg['pause_reason']}" if msg.get("pause_reason") else ""
        drift = "  DRIFTING" if msg.get("drifting") else ""
        return (f"{msg['state']:<14s} level {msg['level']:2d}  {msg['mode']:<9s} target {msg['target']:<6s} "
                f"trials {msg['trials']:3d}  correct {msg['accuracy']:.0%}  "
                f"mean RT {msg['mean_rt_ms']:.0f} ms{drift}{extra}")
    return json.dumps(msg)


def main(argv=None):
    p = argparse.ArgumentParser(description="Send a command to the NeuroWalk Quest app")
    p.add_argument("--quest", required=True, help="Quest IP address shown on the headset panel")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("command", choices=["ping", "start", "pause", "recenter", "level", "mode", "marker", "watch"])
    p.add_argument("value", nargs="?", help="level number, mode name or marker label")
    args = p.parse_args(argv)

    if args.command in ("level", "mode") and args.value is None:
        p.error(f"'{args.command}' needs a value")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    target = (args.quest, args.port)
    sock.sendto(json.dumps(build_message(args.command, args.value)).encode(), target)

    # The Quest replies to whoever spoke last; keep pinging while watching.
    deadline = None if args.command == "watch" else time.time() + 2.0
    got_reply = False
    last_ping = time.time()
    try:
        while deadline is None or time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                if args.command == "watch" and time.time() - last_ping > 5:
                    sock.sendto(json.dumps({"cmd": "ping"}).encode(), target)
                    last_ping = time.time()
                continue
            got_reply = True
            print(describe(json.loads(data.decode())))
            if deadline is not None:
                break
    except KeyboardInterrupt:
        pass

    if not got_reply:
        print(f"No reply from {args.quest}:{args.port}. Is the app running on the Quest, "
              "is the PC on the same Wi-Fi, and is the IP right?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
