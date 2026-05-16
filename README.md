# NTE Auto Fisher for macOS

NTE Auto Fisher is a macOS desktop app for running the NTE fishing loop with a small CustomTkinter GUI.

The app is intentionally simpler than the previous CLI-first build:

- Normal control is now through the GUI: select the NTE window, press **Start Unlimited**, and press **Stop** when done.
- Keyboard actions use targeted PID events through `CGEventPostToPid`, which can still work in the background on macOS.
- The final `init_start` mouse click uses foreground HID mouse input because macOS does not reliably deliver coordinate mouse clicks through `CGEventPostToPid`.
- The bot clicks `init_start` once and immediately returns to State 1 on the next loop. It no longer retries or waits for `start_fishing` confirmation after that click.
- Runs are unlimited by default.

## Fishing loop

The bot repeats this sequence until stopped:

1. Detect `images/start_fishing.png`, then press `F` with PID keyboard input.
2. Confirm `images/start_fishing.png` disappears, then detect `images/catch_now.png` and press `F` with PID keyboard input.
3. Wait for `images/time_to_open_map.png` briefly, then press the configured map key exactly once, default `M`.
4. Detect either `images/return.png` or `images/failed_catch.png`, then press `ESC`, wait, and press `ESC` again.
5. Wait the recast delay, then press `F`.
6. Detect `images/init_start.png`, activate the NTE app, click the center once with foreground HID mouse input, then return to step 1.

The GUI and logs show session totals for completed loops: `images/return.png` counts as a successful loop, and `images/failed_catch.png` counts as a failed/fish-gone loop.

## Requirements

- macOS.
- Python 3.10+.
- The NTE window must be open and not minimized.
- Template images must exist in `images/`:
  - `images/start_fishing.png`
  - `images/catch_now.png`
  - `images/time_to_open_map.png`
  - `images/return.png`
  - `images/failed_catch.png`
  - `images/init_start.png`

## macOS permissions

Grant these permissions to the terminal, IDE, Python runner, or packaged app that runs the bot:

1. **Accessibility**
   - Needed for synthetic keyboard and mouse input.
   - System Settings → Privacy & Security → Accessibility → enable Terminal, iTerm, VS Code, Python, or `NTE Auto Fisher.app`.

2. **Screen Recording**
   - Needed for window screenshots used by template detection.
   - System Settings → Privacy & Security → Screen Recording → enable Terminal, iTerm, VS Code, Python, or `NTE Auto Fisher.app`.

Restart the terminal, IDE, or app after changing permissions.

## Install and run from source

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m nte_fisher
```

## GUI usage

1. Open NTE and make sure the fishing UI can appear.
2. Start the app with `python -m nte_fisher` or open the packaged app.
3. Keep **Window query** as `NTE` unless your process/window is named differently.
4. Press **Refresh Windows**.
5. Pick the correct target window from **Target window**.
   - If the app itself appears in the dropdown as `NTE Auto Fisher`, do not select it; choose the game window instead.
6. Adjust only the simple settings if needed:
   - **Threshold**: template match threshold, default `0.80`.
   - **Scan interval**: normal polling interval, default `0.08` seconds.
   - **Catch scan**: fast polling interval for `catch_now`, default `0.03` seconds.
   - **Map key**: key sent after catch, default `m`.
   - **Dry run**: detect and log without sending input.
7. Press **Start Unlimited**.
8. Press **Stop** to request a cooperative stop.

The bot may take up to a fraction of a second to stop while it is sleeping or scanning. Long sleeps are broken into short stop-checking chunks.

## Why mouse clicks are foreground-only

macOS does not reliably support coordinate mouse clicks posted with `CGEventPostToPid`. Keystrokes can work with PID targeting, but coordinate mouse events are usually discarded or misrouted unless the target app owns the active desktop input path.

Because of that limitation, this app uses a hybrid approach:

- Keyboard: PID mode, background-capable where the game accepts it.
- Mouse: HID mode with target activation, only for the one `init_start` click.

This avoids repeated click attempts and makes the behavior predictable: when the app reaches `init_start`, it activates NTE, clicks once, and returns to the next cycle.

## Diagnostic CLI commands

The CLI remains available for diagnostics and development, but the GUI is the normal control surface.

List matching windows:

```bash
source .venv/bin/activate
python -m nte_fisher.cli list-windows --query NTE
```

Save a background capture:

```bash
source .venv/bin/activate
python -m nte_fisher.cli capture-test --query NTE --out artifacts/nte_capture.png
```

Test all templates:

```bash
source .venv/bin/activate
python -m nte_fisher.cli detect-test --query NTE --all --threshold 0.80
```

Test one PID keyboard event:

```bash
source .venv/bin/activate
python -m nte_fisher.cli input-test --query NTE --key f --input-mode pid --event-source-state hid --hold-seconds 0.10 --yes
```

A hidden `run` subcommand still exists for developer troubleshooting, but it is no longer documented as the normal way to control the app.

## Run tests

```bash
source .venv/bin/activate
python -m pytest -q
```

## Build the macOS app and DMG

Install dependencies and `create-dmg`:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
brew install create-dmg
```

Build the app bundle and DMG:

```bash
chmod +x scripts/build_dmg.sh
scripts/build_dmg.sh
```

Outputs:

- `dist/NTE Auto Fisher.app`
- `dist/NTE Auto Fisher.dmg`

If `create-dmg` is not installed, the build script still creates the `.app` bundle and prints the Homebrew install command for DMG creation.

## Troubleshooting

- **No windows found**: make sure NTE is open, not minimized, and the query matches the owner or window title.
- **The bot selects `NTE Auto Fisher` instead of the game**: press Refresh Windows and choose the actual game window from the dropdown. The app filters itself when possible, but a broad query can still show multiple matches.
- **Capture is blank or fails**: grant Screen Recording permission and restart the app.
- **Keyboard actions do nothing**: press **Request Permissions**, grant Accessibility permission for `NTE Auto Fisher`, then restart the app. Some games reject synthetic background keys even when macOS delivers them.
- **Accessibility is enabled but the app still logs `Accessibility trusted=False`**: remove `NTE Auto Fisher.app` from Accessibility with the minus button, press **Request Permissions** again, re-enable the app, then fully quit and reopen it. This can happen after rebuilding a local, ad-hoc signed `.app` because macOS keeps a stale TCC permission entry.
- **The app briefly steals focus at the end of each cycle**: expected. The `init_start` mouse click must use foreground HID input on macOS.
- **Template never detects**: run `detect-test --all`, verify the template images match your UI scale/language/state, and adjust the GUI threshold.
