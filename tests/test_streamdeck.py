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

    def test_alsa_control_reads_firmware_decibel_range(self):
        output = ("numid=5,iface=MIXER,name='PCM Capture Volume'\n"
                  "  ; type=INTEGER,access=rw---R--,values=1,min=0,max=80,step=0\n"
                  "  : values=40\n"
                  "  | dBminmax-min=0.00dB,max=30.00dB\n")
        completed = module.subprocess.CompletedProcess([], 0, stdout=output)
        with mock.patch.object(module.subprocess, "run", return_value=completed):
            control = module.read_alsa_control(0, "PCM Capture Volume")
        self.assertEqual({"value": 40, "min": 0, "max": 80, "percent": 50, "dbMin": 0.0, "dbMax": 30.0}, control)

    def test_wave_neo_gain_uses_pcm_capture_controls(self):
        controls = {"PCM Capture Volume": {"value": 40, "min": 0, "max": 80, "percent": 50, "dbMin": 0.0, "dbMax": 30.0},
                    "PCM Capture Switch": {"on": False}}
        with mock.patch.object(module, "read_alsa_control", side_effect=lambda card, name: controls.get(name)):
            wave = module.read_wave_controls(0)
        self.assertEqual("PCM Capture Volume", wave["gainControl"])
        self.assertEqual("PCM Capture Switch", wave["muteControl"])
        self.assertEqual(15.0, wave["gainDb"])
        self.assertEqual(30.0, wave["gainDbMax"])
        self.assertTrue(wave["muted"])

    def test_wave_three_gain_keeps_mic_capture_controls(self):
        controls = {"Mic Capture Volume": {"value": 40, "min": 0, "max": 80, "percent": 50},
                    "Mic Capture Switch": {"on": True}}
        with mock.patch.object(module, "read_alsa_control", side_effect=lambda card, name: controls.get(name)):
            wave = module.read_wave_controls(2)
        self.assertEqual("Mic Capture Volume", wave["gainControl"])
        self.assertEqual(20.0, wave["gainDb"])
        self.assertFalse(wave["muted"])

    def wave_neo(self, raw=40):
        return {"card": 0, "gainRaw": raw, "gainMin": 0, "gainMax": 80, "gainDbMin": 0.0, "gainDbMax": 30.0,
                "gainControl": "PCM Capture Volume", "muteControl": "PCM Capture Switch"}

    def test_wave_neo_gain_step_is_one_decibel(self):
        with mock.patch.object(module, "set_alsa_control") as setter:
            module.perform_wave_action(self.wave_neo(40), "wave_gain_up")
            module.perform_wave_action(self.wave_neo(80), "wave_gain_up")
            module.perform_wave_action(self.wave_neo(2), "wave_gain_down")
        self.assertEqual([mock.call(0, "PCM Capture Volume", 43), mock.call(0, "PCM Capture Volume", 80),
                          mock.call(0, "PCM Capture Volume", 0)], setter.call_args_list)

    def test_wave_neo_presets_convert_decibels_to_its_range(self):
        with mock.patch.object(module, "set_alsa_control") as setter:
            for action in ("wave_preset_quiet", "wave_preset_normal", "wave_preset_loud"):
                module.perform_wave_action(self.wave_neo(), action)
        self.assertEqual([mock.call(0, "PCM Capture Volume", 80), mock.call(0, "PCM Capture Volume", 53),
                          mock.call(0, "PCM Capture Volume", 27)], setter.call_args_list)

    def test_wave_neo_mute_toggles_its_capture_switch(self):
        with mock.patch.object(module, "set_alsa_control") as setter:
            module.perform_wave_action(self.wave_neo(), "wave_mute")
        setter.assert_called_once_with(0, "PCM Capture Switch", "toggle")

    def test_wave_three_presets_are_unchanged(self):
        wave = {"card": 2, "gainRaw": 40, "sourceId": 89}
        with mock.patch.object(module, "set_alsa_control") as setter:
            for action in ("wave_preset_quiet", "wave_preset_normal", "wave_preset_loud"):
                module.perform_wave_action(wave, action)
        self.assertEqual([mock.call(2, "Mic Capture Volume", 60), mock.call(2, "Mic Capture Volume", 40),
                          mock.call(2, "Mic Capture Volume", 20)], setter.call_args_list)

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
            "root.selectedLightName(); textFormat: Text.PlainText",
            "root.status.wave.product : \"Wave microphone\"; textFormat: Text.PlainText",
            "root.status.profile || \"Omarchy Default\"; textFormat: Text.PlainText",
            "text: modelData.label; textFormat: Text.PlainText",
            "root.actionName(modelData.action); textFormat: Text.PlainText",
            'text: root.error || root.status.error || ""; textFormat: Text.PlainText',
        )
        for binding in bindings:
            self.assertIn(binding, panel, f"untrusted QML binding lacks PlainText: {binding}")

    def test_wave_is_named_after_the_detected_model(self):
        """A Wave Neo must not be labelled Wave:3 in the device picker or inspector."""
        self.assertNotIn('"Wave:3"', self.PANEL.read_text())

    def test_wave_or_lights_alone_count_as_connected(self):
        panel = self.PANEL.read_text()
        line = next(x for x in panel.splitlines() if "readonly property bool connected:" in x)
        self.assertIn("hasWave", line)
        self.assertIn("hasLights", line)

    def test_bar_status_is_polled_while_the_panel_is_closed(self):
        """The bar icon reads `connected` from the panel, so status must refresh while it is closed."""
        panel = self.PANEL.read_text()
        timer = next(x for x in panel.splitlines() if x.strip().startswith("Timer {") and "refresh" in x)
        self.assertNotIn("running: root.opened", timer)


if __name__ == "__main__":
    unittest.main()
