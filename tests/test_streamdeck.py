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

    def test_malformed_key_entries_draw_blank_and_do_nothing(self):
        profile = paged_profile(pages=1)
        profile["keys"][1] = None
        daemon = self.make_daemon(profile)
        drawn = []
        with mock.patch.object(module.Daemon, "key_image", lambda self, dev, index, key, spec: drawn.append(key["action"])), \
             mock.patch.object(module.Daemon, "update_screen"):
            daemon.decorate(self.neo())
        daemon.parse_deck(neo_report(keys=[1]), self.neo())
        self.assertEqual("", drawn[1])
        self.assertEqual([], daemon.actions)

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

    def test_malformed_pages_read_as_empty(self):
        self.assertEqual(1, module.page_count({"pages": {"2": []}}))
        self.assertEqual([], module.page_keys({"keys": "abc"}, 0))
        self.assertEqual([], module.page_keys({"pages": ["abc"]}, 1))
        self.assertEqual([], module.page_keys({"pages": [{"keys": 5}]}, 1))

    def test_a_page_cannot_be_added_to_malformed_pages(self):
        path = self.with_profile({"keys": [], "pages": {"2": []}})
        with self.assertRaises(ValueError): module.add_page()
        self.assertEqual({"2": []}, module.json.loads(path.read_text())["pages"])

    def test_key_slots_grow_on_every_page(self):
        profile = {"keys": [], "pages": [{"keys": []}]}
        self.assertTrue(module.ensure_key_slots(profile, 8))
        self.assertEqual([8, 8], [len(profile["keys"]), len(profile["pages"][0]["keys"])])


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
        self.assertIn("model: root.pageKeys(root.editPage).slice(0, root.deckKeys)", panel)
        self.assertIn('"--page", String(root.editPage + 1)', panel)
        self.assertIn("(root.pageKeys(root.editPage)[root.selectedIndex] || {}).action", panel)

    def test_editor_reads_malformed_pages_as_empty(self):
        panel = self.PANEL.read_text()
        self.assertIn("readonly property var extraPages: Array.isArray(profile.pages) ? profile.pages : []", panel)
        self.assertIn("return Array.isArray(keys) ? keys : []", panel)

    def test_panels_without_page_tabs_edit_page_one(self):
        self.assertIn("readonly property int editPage: hasPages ? selectedPage : 0", self.PANEL.read_text())

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


if __name__ == "__main__":
    unittest.main()
