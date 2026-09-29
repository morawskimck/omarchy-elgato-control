# Changelog

## Unreleased

- Support the Wave Neo: find its gain and mute under the `PCM Capture` mixer names it exposes instead of the Wave:3's `Mic Capture` ones, read gain in dB from the range the firmware reports, and convert the 1 dB gain step and the presets to that range.
- Name the Wave device page after the detected model instead of always showing Wave:3.
- Count a Wave or a reachable Key Light as connected, and keep polling status while the panel is closed, so the bar icon no longer shows Disconnected until the panel is first opened.

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
