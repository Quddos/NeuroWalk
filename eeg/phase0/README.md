# NeuroWalk AR — Phase 0: your first EEG recording

Goal: put the Emotiv EPOC X on, get good contact, and record 60 s with eyes open
followed by 60 s with eyes closed. If the alpha rhythm at the back of the head
(sensors **O1** and **O2**) goes up when your eyes close, the setup works. This is
the **Berger effect**, the oldest and most reliable result in EEG, which makes it a
good first check.

This run also tells us which data streams your free Emotiv account can use.

Files in this folder:

| File | What it is |
|---|---|
| `phase0_record.py` | The recording script |
| `test_phase0.py` | Offline tests (no headset needed) |
| `cortex_credentials.example.json` | Template for your Cortex App keys |
| `cortex_credentials.json` | **You create this.** Your real keys. Git ignores it, so never share it. |
| `recordings/` | CSV output (created on the first run, also ignored by git) |

> When this guide and EMOTIV Launcher disagree, go with **Launcher's built-in
> fitting guide**. It's made for your exact headset. This guide only gives an
> overview so you know what to expect.

---

## Part 1 — Fitting the EPOC X

### 1. Charge it
- Charge the headset fully before your first session, using the cable that came
  with it. Launcher shows the battery level once the headset is connected.
  A full charge lasts several hours.
- You can't wear the headset while it's charging, so charge it beforehand.

### 2. Hydrate the felt sensors
The EPOC X uses small felt pads soaked in saline. Wet felt is what conducts the
tiny brain signals from your scalp to the sensor.

- Use **saline solution**: the bottle in the kit, or multipurpose contact-lens
  saline from a pharmacy. Tap water conducts poorly and leaves deposits.
- Put the felt pads into the sensor holders on the arms if they aren't already
  there. Launcher shows how they twist in.
- Wet every pad until it's **soaked through but not dripping**. Squeeze the
  dropper slowly and let the felt absorb it. If drops run off, it's too wet. Dab
  off the extra with a tissue.
  - Too dry means bad contact (red or black in Launcher).
  - Too wet means saline can run between sensors and short them together, and it
    can get into the electronics. Keep drips away from the headset body.
- Do the two **reference sensors** too (the ones that sit behind the ears). They
  matter most. If they're poor, every channel is poor.

### 3. Put it on
1. Hold the headset with both hands, open the arms a little and lower it from
   above, front first.
2. **Front sensors**: these should sit about **three finger widths above your
   eyebrows**. Put three fingers flat above an eyebrow. The front sensor goes just
   above your top finger.
3. **References**: slide them onto the **bony bump just behind each ear** (the
   mastoid bone), not on the soft skin or the ear itself.
4. Check that it's centred. The headset should sit even from left to right, with
   the middle of the front in line with your nose.
5. **Part the hair under each sensor.** This is the most important step if you
   have thick or long hair. Gently wiggle each sensor side to side so the felt
   pushes through the hair onto the scalp. You can also lift the arm, move the
   hair aside with a finger, and set it back down. The back sensors (O1/O2) often
   need the most work, and they're exactly the ones this test uses.

The headset should feel snug but not painful. Take it off if it hurts or your
skin gets irritated.

### 4. Switch on and connect in EMOTIV Launcher
1. **Plug the USB dongle into the PC.** Use the dongle rather than Bluetooth. It's
   more reliable and its sample rate is steadier. A front USB port or a short USB
   extension near you helps.
2. Switch the headset on. The power switch is on the headset body. If you can't
   find it, check Launcher's guide or the quick-start card in the box. A light
   shows that it's on.
3. Open **EMOTIV Launcher** and log in. Your headset (serial ending
   **…E502101F**) should appear in the device list. Click **Connect**. If it asks,
   choose the dongle connection.
4. Launcher may ask you to update the firmware. Let it finish before continuing.

### 5. Get the contact-quality map to green
Launcher shows a head map with a dot for each sensor:

- **Green**: good. **Yellow/orange**: fair. **Red**: poor. **Black**: no contact.
- Start with the **references**. Until they're green, the other sensors can't
  read well.
- For each red or black sensor, wiggle it through the hair and add **one** drop of
  saline if the pad feels dry. Give it 10–20 seconds to settle before you judge it.
- Aim for **all green**. For this test, **O1 and O2 must be green**. A couple of
  yellow sensors elsewhere is okay for a first try.
- Pads dry out over 30–60 minutes. If sensors fade later, re-wet them.

Launcher also shows a percentage for overall contact quality. The script prints
the same numbers before it starts.

### After the session
Switch the headset off. Take the felt pads out, rinse them in water and let them
air-dry. Wipe the sensor holders dry. Charge the headset for next time.

---

## Part 2 — One-time setup: a free Cortex App

The script talks to the **Cortex** service, which EMOTIV Launcher runs on this PC.
For Cortex to accept a connection, the script needs an app ID. Creating one is
free:

1. Sign in at **emotiv.com** with the same account you use in Launcher.
2. Find **Cortex Apps** in your account area and **register a new app**. Any name
   works, e.g. `NeuroWalk Phase0`.
3. You'll get a **Client ID** and a **Client Secret**. Treat the secret like a
   password.
4. In this folder, copy `cortex_credentials.example.json` to
   `cortex_credentials.json` and paste the two values in (keep the quotes).
   Don't paste them into any chat, including with Claude.

   You can use environment variables instead of the file:
   `EMOTIV_CLIENT_ID` and `EMOTIV_CLIENT_SECRET`.

The first time you run the script, **EMOTIV Launcher asks you to approve the app**.
Click Approve. The script waits for you.

---

## Part 3 — Running the recording

Optional first step: check everything works on this PC with fake data. This
takes about 30 seconds and doesn't need the headset.

```bash
py phase0_record.py --mock --yes --open-seconds 10 --closed-seconds 10
```

The real recording (headset on, sensors green, Launcher running):

```bash
py phase0_record.py
```

What happens:

1. It connects to Cortex, authorises, finds your headset and opens a session.
2. It lists which streams your account allows:
   - `pow` — band power (theta, alpha, low beta, high beta, gamma per sensor)
   - `eq` — contact quality per sensor, plus battery
   - `mot` — motion sensor (needed later to reject artefacts while walking)
   - `eeg` — raw EEG. This usually needs a paid licence. If it's refused, the
     script says so and carries on, because Phase 0 only needs `pow`.
3. It prints the contact quality and waits. Fix any weak sensors, type `r` and
   press Enter to refresh, then press **Enter** to start.
4. **One beep**: eyes **open** for 60 s. Look softly at one spot. Blink normally,
   and don't talk, chew or clench your jaw.
5. A prompt, then **two beeps**: **close** your eyes for 60 s. Stay relaxed and
   awake.
6. **Three beeps**: done, open your eyes.
7. It saves the CSVs in `recordings/` and prints the result:

```
  sensor      eyes open  eyes closed  closed/open
  O1              ...          ...        1.8x
  O2              ...          ...        1.7x

  PASS - alpha is 1.75x higher with eyes closed. ...
```

**PASS** means alpha rose with your eyes closed, so the sensors are picking up
real brain activity. **FAIL** usually means poor contact at O1/O2 or the
references. Re-seat and re-wet them, get them green, and run it again. The
first 5 s of each phase are left out because the eyes are just opening or
closing.

### Output files
Each run writes `recordings/<date_time>_<stream>.csv`, one file for each allowed
stream, plus `<date_time>_summary.json`. Every row has:

- `cortex_time`: the headset timestamp from Cortex (Unix seconds)
- `host_time`: when this PC received the sample
- `phase`: `pre`, `eyes_open`, `transition`, `eyes_closed` or `post`
- `phase_elapsed_s`: seconds since that phase started
- then the stream's own columns, using the names Cortex reports (for example
  `O1/alpha`)

The summary JSON records which streams were allowed or refused and the alpha
result.

To re-check a saved file later:

```bash
py phase0_record.py --analyze recordings/<date_time>_pow.csv
```

### Troubleshooting
| Message | What to do |
|---|---|
| `Could not reach Cortex at wss://localhost:6868` | Open EMOTIV Launcher and log in. |
| `No Cortex credentials found` | Create `cortex_credentials.json` (Part 2). |
| Waiting for approval | Click **Approve** in the Launcher pop-up. |
| `No connected headset` | Switch the headset on, plug in the dongle, click Connect in Launcher. |
| Errors about the licence or EULA from `authorize` | Log in to Launcher and accept any terms it shows, then retry. |
| `eeg NO ...licence...` | Expected on a free account. Phase 0 doesn't need it. |

### Running the offline tests
```bash
py -m unittest test_phase0 -v
```
