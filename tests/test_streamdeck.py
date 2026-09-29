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

    def test_lcd_svg_escapes_dial_labels(self):
        svg = module.lcd_svg({"dials": [{"label": "A&B <c>"}]}, 55, [])
        self.assertIn("A&amp;B &lt;c&gt;", svg)

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

    def test_terminal_action_uses_the_default_terminal(self):
        self.assertEqual(["uwsm-app", "--", "xdg-terminal-exec"], module.command_for("terminal"))

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

    def test_wave_mixer_names_are_probed_once_per_card(self):
        controls = {"PCM Capture Volume": {"value": 40, "min": 0, "max": 80, "percent": 50, "dbMin": 0.0, "dbMax": 30.0},
                    "PCM Capture Switch": {"on": True}}
        reads = []
        def read(card, name):
            reads.append(name); return controls.get(name)
        with mock.patch.object(module, "read_alsa_control", side_effect=read), \
             mock.patch.object(module, "WAVE_CONTROL_NAMES", {}):
            module.read_wave_controls(0)
            reads.clear()
            module.read_wave_controls(0)
        self.assertNotIn("Mic Capture Volume", reads)
        self.assertNotIn("Mic Capture Switch", reads)

    def test_wave_mixer_names_are_probed_again_when_a_card_changes(self):
        with mock.patch.object(module, "WAVE_CONTROL_NAMES", {0: {module.WAVE_GAIN_CONTROLS: "PCM Capture Volume"}}), \
             mock.patch.object(module, "read_alsa_control",
                               side_effect=lambda card, name: {"value": 60, "min": 0, "max": 80, "percent": 75}
                               if name == "Mic Capture Volume" else None):
            name, control = module.first_alsa_control(0, module.WAVE_GAIN_CONTROLS)
        self.assertEqual("Mic Capture Volume", name)

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

    def test_wave_mute_reuses_the_microphone_artwork(self):
        artwork = module.ICONS / "mic_mute.jpg"
        self.assertEqual(str(artwork), module.action_icon("wave_mute"))
        self.assertEqual(artwork, module.rendered_key_image("wave_mute", "Wave Microphone Mute", [220, 65, 65]))

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


class FakeHid:
    def __init__(self):
        self.features, self.writes = [], []
    def feature(self, dev, values): self.features.append(values)
    def write(self, dev, values): self.writes.append(values)


def neo_report(keys=(), touch=()):
    """A Stream Deck Neo input report: 8 key bytes, then the left and right touch sensors."""
    states = [1 if i in keys else 0 for i in range(8)] + [1 if i in touch else 0 for i in ("left", "right")]
    return bytes([0x01, 0x00, len(states), 0x00] + states)


def paged_profile(pages=3):
    keys = [[{"label": "p%dk%d" % (page, key), "action": "page%d_key%d" % (page, key)} for key in range(8)]
            for page in range(pages)]
    return {"keys": keys[0], "pages": [{"keys": page} for page in keys[1:]]}


class StreamDeckNeoTests(unittest.TestCase):
    def make_daemon(self, profile=None, record=True):
        daemon = module.Daemon.__new__(module.Daemon)
        daemon.hid, daemon.previous, daemon.page = FakeHid(), {}, 0
        daemon.profile = profile or paged_profile()
        daemon.status, daemon.devices, daemon.light_states = {}, {}, []
        daemon.brightness = 55
        daemon.actions = []
        if record: daemon.act = daemon.actions.append
        return daemon

    def neo(self):
        spec = module.DEVICE_SPECS[module.NEO]
        return {"path": "/dev/hidraw15", "productId": module.NEO, "serial": "A7BSA42312ZGQ1", "product": "Stream Deck Neo",
                "kind": "streamdeck", "label": spec["label"], "keys": spec["keys"], "columns": spec["columns"],
                "capabilities": spec["capabilities"], "handle": object()}

    def test_neo_is_a_paged_eight_key_panel_with_an_info_screen(self):
        spec = module.DEVICE_SPECS[module.NEO]
        self.assertEqual((8, 4, 96, True), (spec["keys"], spec["columns"], spec["keySize"], spec["flip"]))
        self.assertIn("pages", spec["capabilities"])
        self.assertIn("screen", spec["capabilities"])
        self.assertNotIn("lcd", spec["capabilities"])

    def test_key_press_runs_the_action_on_the_current_page(self):
        daemon = self.make_daemon(); daemon.page = 1
        device = self.neo()
        daemon.parse_deck(neo_report(keys=[2]), device)
        daemon.parse_deck(neo_report(keys=[2]), device)
        self.assertEqual(["page1_key2"], daemon.actions)

    def test_touch_sensors_flip_pages_and_wrap(self):
        daemon = self.make_daemon()
        with mock.patch.object(module.Daemon, "redraw_decks"):
            device = self.neo()
            daemon.parse_deck(neo_report(touch=["left"]), device)
            self.assertEqual(2, daemon.page)
            daemon.parse_deck(neo_report(), device)
            daemon.parse_deck(neo_report(touch=["right"]), device)
            self.assertEqual(0, daemon.page)
            daemon.parse_deck(neo_report(touch=["right"]), device)
            self.assertEqual(0, daemon.page, "a held sensor flips once")
        self.assertEqual([], daemon.actions)

    def test_single_page_profile_does_not_flip(self):
        daemon = self.make_daemon(paged_profile(pages=1))
        with mock.patch.object(module.Daemon, "redraw_decks") as redraw:
            daemon.flip_page(1)
        self.assertEqual(0, daemon.page)
        redraw.assert_not_called()

    def test_page_actions_flip_from_any_control(self):
        daemon = self.make_daemon(record=False)
        with mock.patch.object(module.Daemon, "redraw_decks"):
            daemon.act("page_next"); daemon.act("page_next"); daemon.act("page_prev")
        self.assertEqual(1, daemon.page)
        self.assertTrue(module.valid_action("page_next"))
        self.assertTrue(module.valid_action("page_prev"))

    def test_key_only_panel_keys_are_not_read_as_touch_sensors(self):
        daemon = self.make_daemon()
        report = bytes([0x01, 0x00, 15, 0x00] + [0] * 8 + [1] + [0] * 6)
        daemon.parse_deck(report, {"path": "/dev/hidraw2", "productId": module.MK2, "handle": object()})
        self.assertEqual(0, daemon.page)

    def test_decorate_draws_the_current_page_and_lights_the_touch_sensors(self):
        daemon = self.make_daemon(); daemon.page = 2
        drawn = []
        with mock.patch.object(module.Daemon, "key_image", lambda self, dev, index, key, spec: drawn.append(key["action"])), \
             mock.patch.object(module.Daemon, "update_screen"):
            daemon.decorate(self.neo())
        self.assertEqual(["page2_key%d" % i for i in range(8)], drawn)
        self.assertEqual({8, 9}, {f[2] for f in daemon.hid.features if f[:2] == [0x03, 0x06]})

    def test_short_page_is_drawn_blank_past_its_last_key(self):
        profile = paged_profile(pages=2)
        profile["pages"][0]["keys"] = profile["pages"][0]["keys"][:3]
        daemon = self.make_daemon(profile); daemon.page = 1
        drawn = []
        with mock.patch.object(module.Daemon, "key_image", lambda self, dev, index, key, spec: drawn.append(key["action"])), \
             mock.patch.object(module.Daemon, "update_screen"):
            daemon.decorate(self.neo())
        self.assertEqual(["page1_key0", "page1_key1", "page1_key2"] + [""] * 5, drawn)

    def test_live_page_follows_its_keys_when_an_earlier_page_is_removed(self):
        daemon = self.make_daemon(); daemon.page = 2
        old = daemon.profile
        daemon.profile = {"keys": old["pages"][0]["keys"], "pages": [old["pages"][1]]}
        daemon.follow_page(old)
        self.assertEqual(1, daemon.page)

    def test_live_page_keeps_its_place_when_its_keys_are_edited(self):
        daemon = self.make_daemon(); daemon.page = 1
        old = daemon.profile
        daemon.profile = module.json.loads(module.json.dumps(old))
        daemon.profile["pages"][0]["keys"][0]["action"] = "lock"
        daemon.follow_page(old)
        self.assertEqual(1, daemon.page)

    def test_mic_state_is_read_with_device_polling_when_a_screen_is_attached(self):
        daemon = self.make_daemon()
        neo = self.neo(); daemon.devices = {neo["path"]: neo}
        daemon.hid.paths = lambda: [{k: v for k, v in neo.items() if k != "handle"}]
        with mock.patch.object(module, "detect_wave", return_value=None), \
             mock.patch.object(module, "mic_muted", return_value=True) as muted:
            daemon.connect()
        muted.assert_called_once_with(None)
        self.assertTrue(daemon.status["micMuted"])

    def test_paged_upload_carries_command_index_and_page_numbers(self):
        daemon = self.make_daemon()
        daemon.write_paged(object(), 0x07, 3, bytes(1017))
        self.assertEqual([[0x02, 0x07, 3, 0, 1016 & 255, 1016 >> 8, 0, 0], [0x02, 0x07, 3, 1, 1, 0, 1, 0]],
                         [w[:8] for w in daemon.hid.writes])

    def test_single_page_profile_leaves_touch_sensors_dark(self):
        daemon = self.make_daemon(paged_profile(pages=1))
        with mock.patch.object(module.Daemon, "key_image"), mock.patch.object(module.Daemon, "update_screen"):
            daemon.decorate(self.neo())
        touch = [f for f in daemon.hid.features if f[:2] == [0x03, 0x06]]
        self.assertEqual([[0x03, 0x06, 8, 0, 0, 0], [0x03, 0x06, 9, 0, 0, 0]], touch)

    def test_window_image_is_sent_in_paged_reports(self):
        daemon = self.make_daemon()
        daemon.write_window(object(), bytes(range(256)) * 6)  # 1536 bytes
        self.assertEqual(2, len(daemon.hid.writes))
        self.assertEqual([0x02, 0x0B, 0, 0, 1016 & 255, 1016 >> 8, 0, 0], daemon.hid.writes[0][:8])
        self.assertEqual([0x02, 0x0B, 0, 1, 520 & 255, 520 >> 8, 1, 0], daemon.hid.writes[1][:8])
        self.assertEqual(1024, len(daemon.hid.writes[1]))

    def test_info_screen_shows_clock_page_and_status(self):
        now = module.time.struct_time((2026, 9, 29, 14, 32, 0, 1, 272, 0))
        svg = module.neo_screen_svg(now, page=1, pages=3, mic_muted=True, lights=[{"reachable": True, "on": 1, "brightness": 65}])
        self.assertIn('width="248" height="58"', svg)
        self.assertIn("14:32", svg)
        self.assertIn("2/3", svg)
        self.assertIn("MUTED", svg)
        self.assertIn("65%", svg)

    def test_info_screen_omits_page_count_for_one_page(self):
        now = module.time.struct_time((2026, 9, 29, 9, 5, 0, 1, 272, 0))
        svg = module.neo_screen_svg(now, page=0, pages=1, mic_muted=False, lights=[])
        self.assertIn("09:05", svg)
        self.assertNotIn("1/1", svg)
        self.assertNotIn("MUTED", svg)

    def test_profile_reload_keeps_the_page_in_range(self):
        daemon = self.make_daemon(); daemon.page = 2
        daemon.profile = paged_profile(pages=2)
        daemon.clamp_page()
        self.assertEqual(1, daemon.page)


class PageProfileTests(unittest.TestCase):
    def with_profile(self, profile):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = pathlib.Path(directory.name)
        path = config / "profile.json"
        path.write_text(module.json.dumps(profile))
        for name, value in (("CONFIG", config), ("PROFILE", path)):
            patcher = mock.patch.object(module, name, value); patcher.start(); self.addCleanup(patcher.stop)
        return path

    def test_page_one_is_the_keys_list(self):
        profile = paged_profile(pages=2)
        self.assertIs(profile["keys"], module.page_keys(profile, 0))
        self.assertIs(profile["pages"][0]["keys"], module.page_keys(profile, 1))
        self.assertEqual(2, module.page_count(profile))
        self.assertEqual(1, module.page_count({"keys": []}))

    def test_added_page_matches_page_one_size(self):
        path = self.with_profile(paged_profile(pages=1))
        self.assertEqual(2, module.add_page())
        saved = module.json.loads(path.read_text())
        self.assertEqual(8, len(saved["pages"][0]["keys"]))
        self.assertEqual("", saved["pages"][0]["keys"][0]["action"])

    def test_removing_page_one_promotes_page_two(self):
        path = self.with_profile(paged_profile(pages=3))
        module.remove_page(0)
        saved = module.json.loads(path.read_text())
        self.assertEqual("page1_key0", saved["keys"][0]["action"])
        self.assertEqual(["page2_key0"], [p["keys"][0]["action"] for p in saved["pages"]])

    def test_removing_the_last_extra_page_drops_the_pages_list(self):
        path = self.with_profile(paged_profile(pages=2))
        module.remove_page(1)
        self.assertNotIn("pages", module.json.loads(path.read_text()))

    def test_the_only_page_cannot_be_removed(self):
        self.with_profile(paged_profile(pages=1))
        with self.assertRaises(ValueError): module.remove_page(0)

    def test_set_key_writes_to_the_selected_page(self):
        path = self.with_profile(paged_profile(pages=2))
        module.set_control_action("keys", 3, "action", "lock", page=1)
        saved = module.json.loads(path.read_text())
        self.assertEqual("lock", saved["pages"][0]["keys"][3]["action"])
        self.assertEqual("page0_key3", saved["keys"][3]["action"])
        with self.assertRaises(ValueError): module.set_control_action("keys", 0, "action", "lock", page=2)

    def test_key_slots_grow_on_every_page(self):
        profile = {"keys": [], "pages": [{"keys": []}]}
        self.assertTrue(module.ensure_key_slots(profile, 8))
        self.assertEqual([8, 8], [len(profile["keys"]), len(profile["pages"][0]["keys"])])


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
            "root.selectedLightName(); textFormat: Text.PlainText",
            "root.status.wave.product : \"Wave microphone\"; textFormat: Text.PlainText",
            "root.status.profile || \"Omarchy Default\"; textFormat: Text.PlainText",
            "text: modelData.label; textFormat: Text.PlainText",
            "root.actionName(modelData.action); textFormat: Text.PlainText",
            'text: root.error || root.status.error || ""; textFormat: Text.PlainText',
        )
        for binding in bindings:
            self.assertIn(binding, panel, f"untrusted QML binding lacks PlainText: {binding}")

    def test_key_editor_reads_and_saves_the_selected_page(self):
        panel = self.PANEL.read_text()
        self.assertIn("model: root.pageKeys(root.selectedPage).slice(0, root.deckKeys)", panel)
        self.assertIn('"--page", String(root.selectedPage + 1)', panel)
        self.assertIn("(root.pageKeys(root.selectedPage)[root.selectedIndex] || {}).action", panel)

    def test_page_tabs_appear_only_on_panels_that_can_flip_pages(self):
        panel = self.PANEL.read_text()
        self.assertIn('readonly property bool hasPages: hasDeck && (deck.capabilities || []).indexOf("pages") >= 0', panel)
        tabs = panel[panel.index("Page tabs"):]
        self.assertIn("visible: root.hasPages", tabs[:tabs.index("Repeater")])

    def test_new_page_is_selected_only_once_it_exists(self):
        panel = self.PANEL.read_text()
        add_page = panel[panel.index("function addPage()"):panel.index("function removePage()")]
        self.assertNotIn("root.selectedPage = ", add_page)
        self.assertIn("root.pendingPage = root.pageCount", add_page)

    def test_pages_can_be_added_and_removed_from_the_editor(self):
        panel = self.PANEL.read_text()
        self.assertIn('[root.helper, "add-page"]', panel)
        self.assertIn('[root.helper, "remove-page", String(root.selectedPage + 1)]', panel)

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

    def test_group_brightness_slider_reaches_the_highest_light_limit(self):
        self.assertIn("Math.max.apply(null, limits)", self.PANEL.read_text())

    def test_brightness_slider_stops_at_the_light_limit(self):
        panel = self.PANEL.read_text()
        slider = panel[panel.index("id: lightBrightness"):].split("\n", 1)[0]
        self.assertIn("to: root.selectedLightLimit()", slider)


if __name__ == "__main__":
    unittest.main()
