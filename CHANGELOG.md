# Changelog

## Unreleased

- Add Stream Deck Neo support (`0fd9:009a`): eight 96×96 keys rotated 180°, touch sensors that flip key pages, and an info screen with the clock, page, microphone mute, and Key Light state, redrawn when any of them changes.
- Add key pages to every Stream Deck: page tabs in the editor, `add-page`/`remove-page`/`set-key --page` in the CLI, and Previous Page and Next Page functions. Page 1 remains the profile's `keys` list.
- Share the full-window upload and SVG rendering between the Plus LCD strip and the Neo info screen.
- Add support for key-only Stream Deck panels: MK.2 (including Scissor and Module revisions), Original V2, and XL/XL V2. Key count, grid, artwork size, and the 180-degree artwork rotation the non-Plus gen-2 firmware expects are now per-device, and the profile grows to the attached panel's key count.
- Render key artwork as 3-component sRGB JPEG. ImageMagick emitted a 1-channel grayscale file for monochrome keys, which the panel firmware silently fails to decode: it repainted the last image it decoded, so an unassigned key showed a neighbour's artwork.
- Size the panel editor's key grid from the connected device, hide the dial row on panels without dials, and let the device stage grow past two rows.
- Rebuild the action catalog when the panel opens, so an application installed after the shell started is no longer invisible to the editor until a restart.
- Index the icon themes once per lookup batch instead of globbing them per application, cutting a catalog build on a typical system from ~0.6s to ~0.06s.
- Drop stale per-device key state when a device disconnects, so swapping panels on the same hidraw node cannot crash the daemon.
- Report profile read and write failures during device connect through `status.error` instead of terminating the daemon.
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
