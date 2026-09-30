# Development status and handoff

Last updated: 2026-08-20
Plugin version: 0.3.1
Status: marketplace needs-fixes addressed; Key Light names render as plain text

## Goal

Build an Omarchy Shell plugin that uses a Stream Deck as a native Linux control surface, presents device status in the Oma bar, and controls Elgato Wi-Fi lights without requiring Elgato's Windows/macOS software.

## Work completed

### Omarchy integration

- Created plugin `io.github.amitcpatel.elgato-control` with `bar-widget` and `service` entry points.
- Added a right-side bar widget using the official Elgato mark.
- Added a panel for profile, Plus, Pedal, key/dial/pedal assignments, and Key Light state.
- The service owns and restarts the Python daemon; **Edit profile** opens the user JSON.

### HID backend

- Implemented Python bindings to system `libhidapi-hidraw` using `ctypes`.
- Corrected `hid_device_info` layout for hidapi 0.15 after an initial enumeration crash exposed a pointer/bus-field ordering mismatch.
- Added reconnects, non-blocking polling, signal handling, atomic status writes, Plus key/dial parsing, Pedal parsing, brightness/fill reports, and paged JPEG key-image reports.

### Artwork and lights

- Replaced colored blocks with 120×120 JPEG pictograms and labels for all eight keys.
- Discovered two Key Light Neo devices over `_elg._tcp` mDNS.
- Added local HTTP state reads and grouped power, brightness, warmer, and cooler actions on port 9123.
- Used `.local` names so DHCP address changes do not invalidate the profile.

### 0.3.0 development pass

- Added explicit per-device capabilities so Plus, Pedal, Wave, and light UI is conditional.
- Added an 800×100 JPEG dial strip and the official Plus `0x02/0x0B` window-image upload protocol.
- Added live LCD refresh after light and hardware-brightness changes.
- Added automatic Wave:3 detection through PipeWire and targeted Wave source controls.
- Added automatic `_elg._tcp` IPv4 discovery when no light hosts are pinned.
- Added recent HID report diagnostics and parser regression tests for Pedal report variants.
- Reworked the panel to omit absent hardware sections.
- Added safe in-panel Pedal remapping for common keyboard keys and built-in actions; the middle pedal defaults to VOXtype push-to-talk.
- Added searchable in-panel action pickers for every key, dial direction/press, and pedal, including dynamically discovered desktop applications.
- Replaced the unusable all-controls-at-once matrix with a device preview and selected-control action inspector modeled on Elgato's editor flow.
- Added black-background application key artwork generated from installed desktop icons, with custom built-in art and non-blank initial fallbacks.
- Added native Wave:3 gain, microphone mute, headphone volume/mute, gain presets, default-source selection, and assignable Stream Deck actions.

### Facecam

- Facecams are found in `/sys/class/video4linux` (Elgato vendor, "Facecam" in the product name, capture node index 0). Their settings are standard V4L2 controls read with `v4l2-ctl --list-ctrls-menus` and written with `v4l2-ctl -c`; automatic modes are written before the manual values they unlock, and a manual value its automatic mode overrides is skipped.
- The camera streams exactly while its video streaming interface has a non-zero alternate setting. The processes holding the video node open name the application; scanning `/proc` costs tens of milliseconds, so the daemon scans when streaming starts and every 30 seconds while it goes on. The shell that runs the daemon also hosts the panel's preview, so a stream held only by that process counts as the preview rather than as live.
- The daemon reads the controls when the camera connects, after an action, when the panel stamps `facecam.json`, and every 10 seconds. The panel keeps the `facecam` command's own reading until the daemon's is newer.
- Presets live in the profile under `facecam.presets`; the active preset lives in `~/.local/state/elgato-control/facecam.json`, so applying one does not rewrite the profile and redraw every key.

## Hardware observed on the development machine

| Device | Identifier | Verified result |
| --- | --- | --- |
| Stream Deck Plus | USB `0fd9:0084` | Opens through hidapi and reports connected |
| Stream Deck Pedal | USB `0fd9:0086` | Opens through hidapi and reports connected |
| Key Light Neo Left | mDNS on port 9123 | HTTP state reads succeed |
| Key Light Neo Right | mDNS on port 9123 | HTTP state reads succeed |
| Facecam Neo | USB `0fd9:0081`, firmware 1.58 | Controls read and written with `v4l2-ctl`; privacy sends a blank picture |

At the last check both lights were reachable, off, brightness 40, temperature 143 (about 7000 K). The daemon and shell had no plugin-specific warnings.

## Runtime files

| Path | Purpose |
| --- | --- |
| `~/.config/omarchy/plugins/io.github.amitcpatel.elgato-control` | Installed plugin source |
| `~/.config/elgato-control/profile.json` | Mutable user profile |
| `~/.local/state/elgato-control/status.json` | Daemon status read by the panel |
| `~/.local/state/elgato-control/facecam.json` | Active Facecam preset and the last change time |

## Known limitations and future work

1. Touchscreen tap, press, and flick input is not mapped yet; the Plus window currently provides dial feedback.
2. Key Light polling and mutations are synchronous and can briefly delay HID processing when a configured light is unreachable.
3. A grouped toggle turns every light off when any is on; grouped brightness and temperature step each light from its own level.
4. Only the Stream Deck Plus and Stream Deck Pedal HID report layouts have been verified.
5. Profile shape validation is partial; panel-selected actions are validated, but hand-edited colors and array lengths are not schema checked.
6. Wave vendor-only controls such as Clipguard and low-cut filters are not exposed by ALSA and are not implemented.
7. Packetization, reconnect, and unreachable-device recovery need broader automated coverage despite the current hardware test pass.
8. A camera streams to one application at a time: while the Facecam preview runs, a call cannot open the camera, so the preview stops when the panel closes or leaves the Facecam page.
9. Elgato Camera Hub features beyond the standard V4L2 controls (such as its on-camera presets) use a vendor protocol and are not implemented.

## Validation commands used

```bash
python -m py_compile bin/elgato-control
omarchy plugin validate ~/.config/omarchy/plugins/io.github.amitcpatel.elgato-control
bin/elgato-control status --json
pgrep -af 'elgato-control daemon'
journalctl --user --since '10 seconds ago' --no-pager
```

## Safety notes

- Action execution uses argument arrays and never invokes a shell.
- Key Light requests stay on the local network and require no authentication.
- Status writes are atomic.
- Do not run two daemons against the same hidraw endpoints.
