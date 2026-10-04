import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "bin" / "elgato-control"
loader = importlib.machinery.SourceFileLoader("elgato_control", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class DeviceModelTests(unittest.TestCase):
    def test_plus_capabilities_are_optional_and_explicit(self):
        caps = module.DEVICE_SPECS[module.PLUS]["capabilities"]
        self.assertIn("lcd", caps)
        self.assertIn("dials", caps)
        self.assertNotIn("pedals", caps)

    def test_pedal_capabilities_do_not_assume_lcd(self):
        self.assertEqual(["pedals"], module.DEVICE_SPECS[module.PEDAL]["capabilities"])

    def test_lcd_svg_has_required_dimensions_and_labels(self):
        profile = {"dials": [{"label": "Volume"}, {"label": "Microphone"}]}
        svg = module.lcd_svg(profile, 55, [])
        self.assertIn('width="800" height="100"', svg)
        self.assertIn("Volume", svg)
        self.assertIn("Microphone", svg)

    def test_wave_actions_target_detected_source(self):
        command = module.command_for("mic_mute", {"sourceId": 89})
        self.assertEqual(["wpctl", "set-mute", "89", "toggle"], command)

    def test_mic_actions_fall_back_to_default_source(self):
        command = module.command_for("mic_up")
        self.assertIn("@DEFAULT_AUDIO_SOURCE@", command)

    def test_media_action_uses_native_omarchy_service(self):
        self.assertEqual(["omarchy-shell", "media", "playPause"], module.command_for("media_play_pause"))

    def test_home_key_action_uses_wtype_without_a_shell(self):
        self.assertEqual(["wtype", "-k", "Home"], module.command_for("key_home"))

    def test_voxtype_push_to_talk_has_press_and_release_commands(self):
        self.assertEqual(["voxtype", "record", "start"], module.command_for("voxtype_push_to_talk"))
        self.assertEqual(["voxtype", "record", "stop"], module.release_command_for("voxtype_push_to_talk"))

    def test_desktop_application_launch_is_validated_and_uses_argv(self):
        with mock.patch.object(module, "desktop_file_exists", return_value=True):
            self.assertEqual(["uwsm-app", "--", "gtk-launch", "example.App"],
                             module.command_for("app:example.App"))

    def test_dotted_desktop_icon_name_is_not_treated_as_file_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            icon = root / ".local/share/icons/128x128/apps/com.example.App.png"
            icon.parent.mkdir(parents=True); icon.write_bytes(b"png")
            with mock.patch.object(module.pathlib.Path, "home", return_value=root):
                resolved = module.resolve_icon("com.example.App")
            self.assertEqual(str(icon), resolved)

    def test_set_key_persists_selected_action(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory)
            profile_path = config / "profile.json"
            profile_path.write_text('{"keys":[{"label":"Old","action":"terminal"}]}')
            with mock.patch.object(module, "CONFIG", config), mock.patch.object(module, "PROFILE", profile_path):
                module.set_control_action("keys", 0, "action", "lock")
                saved = module.json.loads(profile_path.read_text())
            self.assertEqual("lock", saved["keys"][0]["action"])

    def test_legacy_profile_is_migrated_to_elgato_control_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            config = root / "elgato-control"
            state = root / "state"
            legacy = root / "omarchy-streamdeck"
            legacy.mkdir()
            (legacy / "profile.json").write_text('{"name":"Migrated","keys":[]}')
            with mock.patch.object(module, "CONFIG", config), mock.patch.object(module, "STATE", state), \
                 mock.patch.object(module, "PROFILE", config / "profile.json"), \
                 mock.patch.object(module, "LEGACY_CONFIG", legacy):
                module.ensure_profile()
                self.assertEqual("Migrated", module.load_profile()["name"])

    def test_wave_gain_action_changes_hardware_control_without_shell(self):
        wave = {"card": 2, "gainRaw": 40, "sourceId": 89}
        with mock.patch.object(module, "set_alsa_control") as setter:
            module.perform_wave_action(wave, "wave_gain_up")
        setter.assert_called_once_with(2, "Mic Capture Volume", 42)

    def test_wave_push_to_default_uses_detected_source(self):
        wave = {"card": 2, "gainRaw": 40, "sourceId": 89}
        with mock.patch.object(module, "set_default_wave_source") as setter:
            module.perform_wave_action(wave, "wave_default")
        setter.assert_called_once_with(89)

    def test_avahi_discovery_keeps_resolved_ipv4_only(self):
        output = "\n".join([
            "=;eth0;IPv4;Key\\032Light\\032Left;_elg._tcp;local;left.local;192.0.2.2;9123;",
            "=;eth0;IPv6;Key Light Left;_elg._tcp;local;left.local;fe80::1;9123;",
            "+;eth0;IPv4;Unresolved;_elg._tcp;local",
        ])
        self.assertEqual([{"name": "Key Light Left", "host": "192.0.2.2", "port": 9123}],
                         module.parse_avahi_lights(output))

    def test_key_light_names_cannot_carry_rich_text_markup(self):
        output = "=;eth0;IPv4;<img\\032src=\"https://evil.example/x\">;_elg._tcp;local;left.local;192.0.2.2;9123;"
        lights = module.parse_avahi_lights(output)
        self.assertEqual("‹img src=\"https://evil.example/x\"›", lights[0]["name"])
        self.assertNotIn("<", lights[0]["name"])
        self.assertNotIn(">", lights[0]["name"])

    def test_http_status_cannot_overwrite_key_light_name_with_markup(self):
        light = {"name": "Desk", "host": "192.168.1.20"}
        with mock.patch.object(module, "light_request", return_value={
            "on": 1, "brightness": 40, "temperature": 200, "name": "<b>hijack</b>",
        }):
            state = module.light_states([light])[0]
        self.assertEqual("Desk", state["name"])

    def test_key_light_hosts_are_local_only(self):
        self.assertEqual("key-light.local", module.validate_light_host("key-light.local."))
        self.assertEqual("192.168.1.20", module.validate_light_host("192.168.1.20"))
        with self.assertRaises(ValueError): module.validate_light_host("example.com")
        with self.assertRaises(ValueError): module.validate_light_host("8.8.8.8")

    def test_key_light_resolution_rejects_public_and_loopback_addresses(self):
        public = [(module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 9123))]
        loopback = [(module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9123))]
        private = [(module.socket.AF_INET, module.socket.SOCK_STREAM, 6, "", ("192.168.1.20", 9123))]
        with mock.patch.object(module.socket, "getaddrinfo", return_value=public):
            with self.assertRaises(ValueError): module.validate_light_resolution("key-light.local", 9123)
        with mock.patch.object(module.socket, "getaddrinfo", return_value=loopback):
            with self.assertRaises(ValueError): module.validate_light_resolution("key-light.local", 9123)
        with mock.patch.object(module.socket, "getaddrinfo", return_value=private):
            self.assertEqual({"192.168.1.20"}, module.validate_light_resolution("key-light.local", 9123))

    def test_key_light_http_redirects_are_rejected(self):
        handler = module.NoRedirectHandler()
        request = module.urllib.request.Request("http://192.168.1.20:9123/elgato/lights")
        with self.assertRaises(module.urllib.error.HTTPError) as caught:
            handler.redirect_request(request, None, 302, "Found", {}, "http://example.com/")
        caught.exception.close()

    def test_individual_key_light_brightness_targets_only_selected_light(self):
        lights = [{"host": "left.local"}, {"host": "right.local"}]
        states = [{"reachable": True, "brightness": 40}, {"reachable": True, "brightness": 50}]
        with mock.patch.object(module, "available_lights", return_value=lights), \
             mock.patch.object(module, "light_states", side_effect=[states, states]), \
             mock.patch.object(module, "light_request") as request:
            module.control_lights("1", "brightness", 72)
        request.assert_called_once_with(lights[1], {"brightness": 72, "on": 1})

    def test_key_light_temperature_converts_kelvin_to_device_mireds(self):
        lights = [{"host": "left.local"}]
        states = [{"reachable": True, "temperature": 200}]
        with mock.patch.object(module, "available_lights", return_value=lights), \
             mock.patch.object(module, "light_states", side_effect=[states, states]), \
             mock.patch.object(module, "light_request") as request:
            module.control_lights("all", "temperature", 5000)
        request.assert_called_once_with(lights[0], {"temperature": 200, "on": 1})


def usb_light_report(body, kind=0x00, index=0, total=1):
    data = body.encode()
    report = bytearray(512)
    report[0:4] = bytes([0x02, index, total, kind])
    report[4:6] = len(data).to_bytes(2, "little")
    report[6:6 + len(data)] = data
    report[6 + len(data)] = 0x03
    return bytes(report)


class UsbKeyLightTests(unittest.TestCase):
    def sysfs(self, root, name, hid_id, serial):
        device = root / name / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text("DRIVER=hid-generic\nHID_ID=%s\nHID_NAME=Elgato\nHID_UNIQ=%s\n" % (hid_id, serial))

    def connect(self, root, name, hid_device):
        """Point a hidraw node at a HID device, as the kernel does on every connection."""
        (root / hid_device).mkdir(exist_ok=True)
        link = root / name / "device"
        link.parent.mkdir(exist_ok=True)
        if link.is_symlink(): link.unlink()
        link.symlink_to(root / hid_device)

    def light_replies(self, *ceilings):
        """Answer each accessory-info request with the next ceiling, repeating the last."""
        ceilings = list(ceilings)
        state = '{"numberOfLights":1,"lights":[{"on":0,"brightness":40,"temperature":238}]}'
        def reply(path, text):
            if text != "GET /elgato/accessory-info": return state
            ceiling = ceilings.pop(0) if len(ceilings) > 1 else ceilings[0]
            return '{"power-info":{"maximumBrightness":%d}}' % ceiling
        return reply

    def test_request_fits_one_framed_report(self):
        frames = module.usb_light_frames("GET /elgato/lights")
        self.assertEqual(1, len(frames))
        self.assertEqual(512, len(frames[0]))
        self.assertEqual(bytes([0x02, 0, 1, 0x03, 18, 0]) + b"GET /elgato/lights" + b"\x03", frames[0][:25])
        self.assertEqual(bytes(512 - 25), frames[0][25:])

    def test_long_request_is_split_across_numbered_reports(self):
        frames = module.usb_light_frames("x" * 600)
        self.assertEqual([(0, 2, 505), (1, 2, 95)], [(f[1], f[2], int.from_bytes(f[4:6], "little")) for f in frames])
        self.assertEqual(0x03, frames[1][6 + 95])

    def test_response_reports_are_joined_in_order(self):
        reports = iter([usb_light_report('{"lights":', index=0, total=2), usb_light_report("[]}", index=1, total=2)])
        self.assertEqual('{"lights":[]}', module.read_usb_light_response(lambda: next(reports)))

    def test_rejected_request_raises_the_device_message(self):
        reports = iter([usb_light_report('{"errors":[{"message":"Invalid parameters","code":-1}]}', kind=0x07)])
        with self.assertRaisesRegex(RuntimeError, "Invalid parameters"):
            module.read_usb_light_response(lambda: next(reports))

    def test_malformed_report_is_rejected(self):
        report = bytearray(usb_light_report("{}"))
        report[8] = 0x00  # trailer marker
        with self.assertRaises(ValueError):
            module.read_usb_light_response(lambda: bytes(report))

    def test_discovery_finds_key_light_neo_hidraw_nodes_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.sysfs(root, "hidraw11", "0003:00000FD9:000000A0", "A7BTB41912OHLU")
            self.sysfs(root, "hidraw15", "0003:00000FD9:0000009A", "A7BSA42312ZGQ1")
            with mock.patch.object(module, "HIDRAW_SYSFS", root):
                lights = module.discover_usb_lights()
        self.assertEqual([{"name": "Key Light Neo", "transport": "usb", "path": "/dev/hidraw11",
                           "serial": "A7BTB41912OHLU"}], lights)

    def test_usb_light_path_must_be_a_key_light_hidraw_node(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.sysfs(root, "hidraw15", "0003:00000FD9:0000009A", "A7BSA42312ZGQ1")
            with mock.patch.object(module, "HIDRAW_SYSFS", root):
                for path in ("/dev/sda", "/dev/hidraw11/../sda", "/dev/hidraw15"):
                    with self.assertRaises(ValueError): module.validate_usb_light(path)

    def test_brightness_is_clamped_to_the_power_source_limit(self):
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        replies = ['{"power-info":{"maximumBrightness":65}}',
                   '{"numberOfLights":1,"lights":[{"on":1,"brightness":65,"temperature":238}]}']
        with mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
             mock.patch.object(module, "USB_LIGHT_INFO", {}), \
             mock.patch.object(module, "usb_light_exchange", side_effect=replies) as exchange:
            state = module.light_request(light, {"brightness": 90, "on": 1})
        self.assertEqual(mock.call("/dev/hidraw11", "GET /elgato/accessory-info"), exchange.call_args_list[0])
        sent = exchange.call_args_list[1].args[1]
        self.assertTrue(sent.startswith("PUT /elgato/lights "))
        self.assertEqual({"numberOfLights": 1, "lights": [{"brightness": 65, "on": 1}]},
                         module.json.loads(sent[len("PUT /elgato/lights "):]))
        self.assertEqual(65, state["brightness"])

    def test_usb_light_state_reports_its_brightness_limit(self):
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        replies = ['{"power-info":{"maximumBrightness":65}}',
                   '{"numberOfLights":1,"lights":[{"on":0,"brightness":40,"temperature":238}]}']
        with mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
             mock.patch.object(module, "USB_LIGHT_INFO", {}), \
             mock.patch.object(module, "usb_light_exchange", side_effect=replies):
            state = module.light_request(light)
        self.assertEqual({"on": 0, "brightness": 40, "temperature": 238, "maxBrightness": 65}, state)

    def test_brightness_ceiling_is_not_read_again_while_the_light_stays_connected(self):
        # Every accessory-info request makes the light send an input event, so
        # re-reading it on a timer kept the desktop from ever going idle.
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        clock = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            self.connect(root, "hidraw11", "0003:0FD9:00A0.0018")
            with mock.patch.object(module, "HIDRAW_SYSFS", root), \
                 mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
                 mock.patch.object(module, "USB_LIGHT_INFO", {}), \
                 mock.patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                 mock.patch.object(module, "usb_light_exchange", side_effect=self.light_replies(65)) as exchange:
                module.light_request(light)
                clock[0] = 3600.0
                self.assertEqual(65, module.light_request(light)["maxBrightness"])
        self.assertEqual(["GET /elgato/accessory-info", "GET /elgato/lights", "GET /elgato/lights"],
                         [call.args[1] for call in exchange.call_args_list])

    def test_brightness_ceiling_is_read_again_when_the_light_reconnects(self):
        # A light plugged into another power source comes back with another ceiling.
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with mock.patch.object(module, "HIDRAW_SYSFS", root), \
                 mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
                 mock.patch.object(module, "USB_LIGHT_INFO", {}), \
                 mock.patch.object(module, "usb_light_exchange", side_effect=self.light_replies(65, 100)):
                self.connect(root, "hidraw11", "0003:0FD9:00A0.0018")
                self.assertEqual(65, module.light_request(light)["maxBrightness"])
                self.connect(root, "hidraw11", "0003:0FD9:00A0.0019")
                self.assertEqual(100, module.light_request(light)["maxBrightness"])

    def test_unexpected_light_state_is_reported_as_an_invalid_response(self):
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        for reply in ('{"numberOfLights":0}', '{"lights":[]}', '{"lights":["on"]}', '[1]'):
            with mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
                 mock.patch.object(module, "USB_LIGHT_INFO", {}), \
                 mock.patch.object(module, "usb_light_exchange", return_value=reply):
                with self.assertRaises(ValueError, msg=reply):
                    module.light_request(light)

    def test_usb_lights_come_before_network_lights(self):
        usb = {"name": "Key Light Neo", "transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        with mock.patch.object(module, "discover_usb_lights", return_value=[usb]), \
             mock.patch.object(module, "load_profile", return_value={"lights": [{"host": "left.local"}]}):
            self.assertEqual([usb, {"host": "left.local"}], module.available_lights())

    def test_daemon_light_actions_reach_usb_lights(self):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.status = {}
        usb = {"name": "Key Light Neo", "transport": "usb", "path": "/dev/hidraw11", "reachable": True, "on": 0}
        offline = {"name": "Desk", "host": "desk.local", "reachable": False}
        daemon.light_states = [usb, offline]
        daemon.refresh_lights = lambda: None
        with mock.patch.object(module, "light_request") as request:
            daemon.act_lights("lights_toggle")
        request.assert_called_once_with(usb, {"on": 1})

    def test_group_brightness_steps_each_light_from_its_own_level(self):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.status = {}
        usb = {"transport": "usb", "path": "/dev/hidraw11", "reachable": True, "brightness": 60, "maxBrightness": 60}
        wifi = {"host": "desk.local", "reachable": True, "brightness": 60}
        daemon.light_states = [usb, wifi]
        daemon.refresh_lights = lambda: None
        with mock.patch.object(module, "light_request") as request:
            daemon.act_lights("lights_brightness_up")
        self.assertEqual([mock.call(usb, {"brightness": 60, "on": 1}), mock.call(wifi, {"brightness": 65, "on": 1})],
                         request.call_args_list)

    def test_group_temperature_steps_each_light_from_its_own_level(self):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.status = {}
        left = {"host": "left.local", "reachable": True, "temperature": 340}
        right = {"host": "right.local", "reachable": True, "temperature": 200}
        daemon.light_states = [left, right]
        daemon.refresh_lights = lambda: None
        with mock.patch.object(module, "light_request") as request:
            daemon.act_lights("lights_warmer")
        self.assertEqual([mock.call(left, {"temperature": 344, "on": 1}), mock.call(right, {"temperature": 210, "on": 1})],
                         request.call_args_list)

    def test_unavailable_accessory_info_falls_back_to_full_brightness(self):
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        replies = [RuntimeError("Key Light: Request not support"),
                   '{"numberOfLights":1,"lights":[{"on":1,"brightness":80,"temperature":238}]}']
        with mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
             mock.patch.object(module, "USB_LIGHT_INFO", {}), \
             mock.patch.object(module, "usb_light_exchange", side_effect=replies):
            self.assertEqual(100, module.light_request(light)["maxBrightness"])

    def test_missing_brightness_ceiling_falls_back_to_full_brightness(self):
        light = {"transport": "usb", "path": "/dev/hidraw11", "serial": "A"}
        replies = ['{"power-info":{"maximumBrightness":null}}',
                   '{"numberOfLights":1,"lights":[{"on":1,"brightness":80,"temperature":238}]}']
        with mock.patch.object(module, "validate_usb_light", side_effect=lambda path: path), \
             mock.patch.object(module, "USB_LIGHT_INFO", {}), \
             mock.patch.object(module, "usb_light_exchange", side_effect=replies):
            self.assertEqual(100, module.light_request(light)["maxBrightness"])

    def test_empty_network_discovery_is_not_repeated_every_poll(self):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.profile, daemon.status, daemon.devices = {}, {}, {}
        daemon.discovered_lights, daemon.last_light_discovery = [], 0
        with mock.patch.object(module, "discover_usb_lights", return_value=[]), \
             mock.patch.object(module, "discover_lights", return_value=[]) as discover:
            daemon.refresh_lights()
            daemon.refresh_lights()
        self.assertEqual(1, discover.call_count)


class PedalParserTests(unittest.TestCase):
    def make_daemon(self):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.previous = {}
        daemon.profile = {"pedals": [{"action": "left"}, {"action": "middle"}, {"action": "right"}]}
        daemon.actions = []
        daemon.releases = []
        daemon.act = daemon.actions.append
        daemon.release = daemon.releases.append
        return daemon

    def test_three_byte_report_press_is_edge_triggered(self):
        daemon = self.make_daemon()
        daemon.parse_pedal(bytes([1, 0, 3, 1, 0, 0]))
        daemon.parse_pedal(bytes([1, 0, 3, 1, 0, 0]))
        daemon.parse_pedal(bytes([1, 0, 3, 0, 0, 0]))
        self.assertEqual(["left"], daemon.actions)
        self.assertEqual(["left"], daemon.releases)

    def test_legacy_padded_report_is_supported(self):
        daemon = self.make_daemon()
        daemon.parse_pedal(bytes([1, 0, 3, 0, 0, 1, 0]))
        self.assertEqual(["middle"], daemon.actions)


class QmlPlainTextTests(unittest.TestCase):
    PANEL = pathlib.Path(__file__).parents[1] / "Panel.qml"

    def test_network_controlled_qml_text_forces_plain_text(self):
        """Key Light names and other external strings must not use AutoText."""
        panel = self.PANEL.read_text()
        bindings = (
            "text: modelData.name; textFormat: Text.PlainText",
            '"K" : "Unavailable"; textFormat: Text.PlainText',
            "root.selectedLightName(); textFormat: Text.PlainText",
            "root.status.wave.product : \"Wave microphone\"; textFormat: Text.PlainText",
            "root.status.profile || \"Omarchy Default\"; textFormat: Text.PlainText",
            "text: modelData.label; textFormat: Text.PlainText",
            "root.actionName(modelData.action); textFormat: Text.PlainText",
            'text: root.error || root.status.error || ""; textFormat: Text.PlainText',
        )
        for binding in bindings:
            self.assertIn(binding, panel, f"untrusted QML binding lacks PlainText: {binding}")

    def test_group_brightness_slider_reaches_the_highest_light_limit(self):
        self.assertIn("Math.max.apply(null, limits)", self.PANEL.read_text())

    def test_brightness_slider_stops_at_the_light_limit(self):
        panel = self.PANEL.read_text()
        slider = panel[panel.index("id: lightBrightness"):].split("\n", 1)[0]
        self.assertIn("to: root.selectedLightLimit()", slider)


if __name__ == "__main__":
    unittest.main()
