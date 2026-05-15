# NTE Auto-Fishing Bot for macOS

This project automates the NTE fishing loop on macOS using native Quartz/CoreGraphics APIs through PyObjC.

It is designed for **terminal-based control** with detailed timestamped logs. It captures the game window in the background, detects template images with OpenCV, and sends targeted keyboard/mouse events to the NTE process.

## What it does

The bot repeats this sequence:

1. Detect `images/start_fishing.png`, then press `F`.
2. Confirm `images/start_fishing.png` disappears, then detect `images/catch_now.png` and immediately press `F`.
3. Wait `250ms`, then press `M` to open the map/menu.
4. Detect `images/return.png`, then press `ESC`, wait `250ms`, press `ESC` again.
5. Wait `1s`, then press `F`.
6. Detect `images/init_start.png`, then click the center of the matched image on the game window.
7. Return to step 1.

## Requirements

- macOS.
- Python 3.10+ recommended.
- The NTE window must be open and not minimized.
- The template files must exist:
  - `images/start_fishing.png`
  - `images/catch_now.png`
  - `images/return.png`
  - `images/init_start.png`

## macOS permissions

Grant these permissions to the terminal or IDE used to run Python:

1. **Accessibility**
   - Needed for synthetic keyboard/mouse events.
   - System Settings → Privacy & Security → Accessibility → enable Terminal, iTerm, VS Code, or your Python runner.

2. **Screen Recording**
   - Needed on modern macOS for window screenshots.
   - System Settings → Privacy & Security → Screen Recording → enable Terminal, iTerm, VS Code, or your Python runner.

After changing permissions, restart the terminal/IDE.

The script logs `Accessibility trusted=True` before sending real input. If this is `False`, macOS will usually block keyboard/mouse events.

## Setup with a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run unit tests

```bash
source .venv/bin/activate
python -m pytest -q
```

## Recommended verification flow

Run each verification step before running the full bot.

### 1. List windows

```bash
source .venv/bin/activate
python -m nte_fisher.cli list-windows --query NTE
```

Expected: a window with owner/process name `NTE`, a PID, a window ID, and bounds.

If multiple windows appear, use `--pid` with the PID shown in Activity Monitor or terminal output.

### 2. Test background screenshot

```bash
source .venv/bin/activate
python -m nte_fisher.cli capture-test --query NTE --out artifacts/nte_capture.png
```

Expected: `artifacts/nte_capture.png` contains the NTE window even if another window is covering it.

### 3. Test template detection

```bash
source .venv/bin/activate
python -m nte_fisher.cli detect-test --query NTE --template images/start_fishing.png
```

Expected: logs show a confidence score and the matched center coordinate when the template is visible.

You can test all templates:

```bash
source .venv/bin/activate
python -m nte_fisher.cli detect-test --query NTE --all
```

If confidence looks unstable with the default OpenCV coefficient matcher, compare the normalized difference matcher:

```bash
source .venv/bin/activate
python -m nte_fisher.cli detect-test --query NTE --all --match-method auto
```

### 4. Test a single targeted key press

This sends a single key to the NTE PID.

```bash
source .venv/bin/activate
python -m nte_fisher.cli input-test --query NTE --key f --input-mode pid --event-source-state hid --hold-seconds 0.10 --yes
```

Available keys: `f`, `m`, `tab`, `b`, `c`, `j`, `k`, `l`, `i`, `o`, `p`, `u`, `n`, `f1`, `f2`, `f3`, `f4`, `esc`.

If `Accessibility trusted=True` is logged but the game does not react, confirm that you are using `--event-source-state hid` and at least `--hold-seconds 0.10`. If it still does not react, test the foreground fallback:

```bash
source .venv/bin/activate
python -m nte_fisher.cli input-test --query NTE --key f --input-mode hid --activate-before-input --yes
```

This fallback brings NTE to the foreground and posts events to the active HID session, so it is **not background-only**.

### 5. Run the bot in dry-run mode first

Dry-run mode performs capture and detection but does not send inputs.

```bash
source .venv/bin/activate
python -m nte_fisher.cli --log-file artifacts/dry-run.log run --query NTE --dry-run --wait-timeout 10
```

### 6. Run the real bot

```bash
source .venv/bin/activate
python -m nte_fisher.cli --log-file artifacts/run.log run --query NTE --threshold 0.80 --scan-interval 0.08 --catch-scan-interval 0.03 --max-cycles 1 --wait-timeout 60
```

The real bot defaults to true background input with `--input-mode pid`, `--event-source-state hid`, and `--key-hold-seconds 0.10`.

If the true background `pid` input mode does not affect NTE on your machine, use the foreground fallback:

```bash
source .venv/bin/activate
python -m nte_fisher.cli --log-file artifacts/run-hid.log run --query NTE --input-mode hid --activate-before-input --threshold 0.80 --max-cycles 1 --wait-timeout 60
```

Stop with `Ctrl+C`.

## Useful options

- `--query NTE`: finds a window whose owner or title contains `NTE`.
- `--pid 36240`: targets a specific process ID.
- `--threshold 0.80`: OpenCV match confidence threshold.
- `--match-method ccoeff`: default normalized coefficient matching. Use `--match-method sqdiff` only if diagnostics show it is better for your templates.
- `--scan-interval 0.08`: normal polling interval in seconds.
- `--catch-scan-interval 0.03`: faster polling interval for `catch_now.png`.
- `--post-start-delay 0.30`: delay after first `F` before scanning for `catch_now.png`.
- `--map-key m`: menu key after catch. If `M` does not open a usable menu on your keybinds, test `--map-key c`, `--map-key f1`, `--map-key f2`, or `--map-key esc`. Avoid `--map-key f3` for this flow because testing showed it opens the market UI, not the desired return/close prompt.
- `--map-key-retries 3`: sends the selected menu key multiple times after catching because the menu key can be ignored during animation.
- `--map-key-retry-delay 0.25`: delay between repeated `M` presses.
- `--input-mode pid`: true background mode using `CGEventPostToPid`.
- `--click-input-mode same`: mouse clicks inherit `--input-mode` by default. Use `--click-input-mode hid --activate-before-click` if NTE ignores background mouse clicks.
- `--event-source-state hid`: create events with `kCGEventSourceStateHIDSystemState` to mimic hardware-level input as closely as Quartz allows.
- `--hold-seconds 0.10`: hold the key down long enough for frame-based games to see the event.
- `--input-mode hid --activate-before-input`: last-resort foreground fallback if the game ignores background PID events.
- `--init-click-retries 2`: the final `init_start` click is confirmed by waiting for `start_fishing`; if the first background click is ignored, the default second attempt uses a foreground HID click.
- `--start-at catch`: start the first cycle from a later phase if you already cast the line manually or during testing.
- `--log-file artifacts/run.log`: duplicate all detailed terminal logs to a file.
- `--max-cycles 3`: run only a fixed number of fishing cycles.
- `--dry-run`: log actions without sending input.
- `--ignore-accessibility-check`: run even if the Accessibility trust check fails.
- `--wait-timeout 10`: optional per-step timeout for testing so the command fails instead of waiting forever.
- `--no-confirm-actions`: disables visual action-effect confirmations. Keep confirmations enabled during normal use.
- `--start-absence-confirm-timeout 8`: timeout for confirming the `start_fishing` prompt disappears after pressing `F`.

## Important notes

- The window can be obscured behind other windows, but it must not be minimized.
- If targeted background input is ignored by the game, macOS may be delivering the events but the game may reject non-focused synthetic input.
- The bot logs every state transition and action with timestamps.
- Retina scaling is handled by mapping captured image pixels back to window bounds before clicking.
