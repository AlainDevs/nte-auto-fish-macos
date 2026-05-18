# NTE Auto Fisher for macOS

NTE Auto Fisher is a macOS desktop app for running the NTE fishing loop with a small CustomTkinter GUI.

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

You must install and run the application from source:

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

## Why mouse clicks are foreground-only

macOS does not reliably support coordinate mouse clicks posted with `CGEventPostToPid`. Keystrokes can work with PID targeting, but coordinate mouse events are usually discarded or misrouted unless the target app owns the active desktop input path.

Because of that limitation, this app uses a hybrid approach:

- Keyboard: PID mode, background-capable where the game accepts it.
- Mouse: HID mode with target activation, only for the one `init_start` click.

This avoids repeated click attempts and makes the behavior predictable: when the app reaches `init_start`, it activates NTE, clicks once, and returns to the next cycle.

## Run tests

```bash
source .venv/bin/activate
python -m pytest -q
```

## Troubleshooting

- **No windows found**: make sure NTE is open, not minimized, and the query matches the owner or window title.
- **The bot selects `NTE Auto Fisher` instead of the game**: press Refresh Windows and choose the actual game window from the dropdown. The app filters itself when possible, but a broad query can still show multiple matches.
- **Capture is blank or fails**: grant Screen Recording permission and restart the app.
- **Keyboard actions do nothing**: press **Request Permissions**, grant Accessibility permission for `NTE Auto Fisher`, then restart the app. Some games reject synthetic background keys even when macOS delivers them.
- **Accessibility is enabled but the app still logs `Accessibility trusted=False`**: remove `NTE Auto Fisher.app` from Accessibility with the minus button, press **Request Permissions** again, re-enable the app, then fully quit and reopen it.
- **The app briefly steals focus at the end of each cycle**: expected. The `init_start` mouse click must use foreground HID input on macOS.
- **Template never detects**: verify the template images match your UI scale/language/state, and adjust the GUI threshold.
