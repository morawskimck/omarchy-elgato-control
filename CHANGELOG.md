# Changelog

## Unreleased

- Add Facecam Neo support (`0fd9:0081`): a Facecam page with the camera's exposure, color, lens, and image settings, read from the camera and written with `v4l2-ctl`, plus a privacy switch, a reset to the camera's defaults, and whether an application is streaming from the camera.
- Show a live preview on the Facecam page while no application uses the camera, in its own QML file so the panel still loads without Qt Multimedia.
- Save camera settings as named presets, apply them from the panel or a key, and apply the active preset again when the camera reconnects.
- Add Facecam Privacy, Zoom In, Zoom Out, Autofocus, Reset Picture, Next Preset, and per-preset functions for keys, dials, and pedals. The Privacy key shows whether privacy is on, and the bar icon gets a dot while the camera is live.
- Add a `facecam` CLI command for the camera's status, settings, functions, and presets.
- Read the status file directly in the panel instead of starting the helper on every poll, and keep polling it every 2 seconds while the panel is closed so the bar icon stays current.

## 0.3.1 — 2026-08-20

- Force `Text.PlainText` for Key Light names and other externally supplied panel strings so QML AutoText cannot load markup or remote resources.
- Sanitize mDNS Key Light names before they enter status JSON, and keep HTTP light payloads from overwriting the advertised name.

## 0.3.0 — 2026-08-20

- Rename the application to Elgato Control for its multi-device scope.
- Adopt the permanent plugin ID `io.github.amitcpatel.elgato-control`, normalized helper and data paths, and automatic migration of existing profiles.
- Add capability-based discovery for Stream Deck Plus, Pedal, Wave:3, and Key Lights.
- Add Stream Deck Plus key artwork, four-dial LCD rendering, and dial controls.
- Add visual key, dial, and Pedal remapping with installed application discovery.
- Add VOXtype push-to-talk Pedal support.
- Add native Wave:3 gain, mute, headphone, preset, and default-source controls.
- Add automatic Key Light discovery and grouped light actions.
- Add grouped and per-light power, brightness, temperature, refresh, and reachability controls to the Key Lights page.
- Restrict Key Light HTTP traffic to resolved local addresses, reject redirects, and bound response sizes.
- Add generated application artwork with safe non-blank fallbacks.
- Add regression tests for device capabilities, input parsing, discovery, application actions, and Wave controls.
- Add screenshots for each supported product view.

## 0.2.0

- Initial working Stream Deck Plus, Pedal, and Key Light prototype.
