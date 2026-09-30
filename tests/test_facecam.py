import importlib.machinery
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "bin" / "elgato-control"
loader = importlib.machinery.SourceFileLoader("elgato_control_facecam", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


# `v4l2-ctl --list-ctrls-menus` from a Facecam Neo (firmware 1.58).
FACECAM_NEO_CONTROLS = """
User Controls

                     brightness 0x00980900 (int)    : min=-30 max=30 step=1 default=0 value=0 flags=has-min-max
                       contrast 0x00980901 (int)    : min=0 max=100 step=1 default=80 value=80 flags=has-min-max
                     saturation 0x00980902 (int)    : min=0 max=127 step=1 default=64 value=64 flags=has-min-max
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
                           gain 0x00980913 (int)    : min=0 max=88 step=1 default=0 value=0 flags=has-min-max
           power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=2 value=1 (50 Hz)
\t\t\t\t0: Disabled
\t\t\t\t1: 50 Hz
\t\t\t\t2: 60 Hz
      white_balance_temperature 0x0098091a (int)    : min=2800 max=7500 step=10 default=5000 value=3700 flags=inactive, has-min-max
                      sharpness 0x0098091b (int)    : min=0 max=255 step=1 default=128 value=128 flags=has-min-max
         backlight_compensation 0x0098091c (int)    : min=0 max=1 step=1 default=0 value=1 flags=has-min-max

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=1 (Manual Mode)
\t\t\t\t1: Manual Mode
\t\t\t\t3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=1 max=2500 step=1 default=156 value=20 flags=has-min-max
     exposure_dynamic_framerate 0x009a0903 (bool)   : default=0 value=0
                   pan_absolute 0x009a0908 (int)    : min=-2592000 max=2592000 step=3600 default=0 value=0 flags=has-min-max
                  tilt_absolute 0x009a0909 (int)    : min=-1458000 max=1458000 step=3600 default=0 value=0 flags=has-min-max
                 focus_absolute 0x009a090a (int)    : min=215 max=445 step=1 default=215 value=445 flags=has-min-max
     focus_automatic_continuous 0x009a090c (bool)   : default=1 value=0
                  zoom_absolute 0x009a090d (int)    : min=100 max=400 step=1 default=100 value=100 flags=has-min-max
                        privacy 0x009a0910 (bool)   : default=0 value=0
"""


def neo_controls():
    return module.facecam_controls(module.parse_v4l2_controls(FACECAM_NEO_CONTROLS))


class ControlParsingTests(unittest.TestCase):
    def test_integer_control_keeps_its_range_and_values(self):
        control = module.parse_v4l2_controls(FACECAM_NEO_CONTROLS)["brightness"]
        self.assertEqual({"type": "int", "min": -30, "max": 30, "step": 1, "default": 0, "value": 0},
                         {key: control[key] for key in ("type", "min", "max", "step", "default", "value")})

    def test_menu_control_lists_its_items_and_reads_the_number(self):
        control = module.parse_v4l2_controls(FACECAM_NEO_CONTROLS)["auto_exposure"]
        self.assertEqual(1, control["value"])
        self.assertEqual([{"value": 1, "label": "Manual Mode"}, {"value": 3, "label": "Aperture Priority Mode"}],
                         control["menu"])

    def test_inactive_flag_is_read(self):
        controls = module.parse_v4l2_controls(FACECAM_NEO_CONTROLS)
        self.assertIn("inactive", controls["white_balance_temperature"]["flags"])
        self.assertNotIn("inactive", controls["saturation"]["flags"])

    def test_unparseable_lines_are_ignored(self):
        self.assertEqual({}, module.parse_v4l2_controls("garbage\n\tnot a control\n"))


class ControlModelTests(unittest.TestCase):
    def test_controls_are_grouped_in_inspector_order(self):
        groups = module.facecam_groups(neo_controls())
        self.assertEqual(["exposure", "color", "lens", "image"], [group["id"] for group in groups])
        self.assertEqual(["auto_exposure", "exposure_time_absolute", "gain", "exposure_dynamic_framerate",
                          "power_line_frequency", "backlight_compensation"], groups[0]["controls"])

    def test_unknown_controls_are_dropped_and_privacy_is_kept_outside_the_groups(self):
        parsed = module.parse_v4l2_controls(FACECAM_NEO_CONTROLS)
        parsed["led1_mode"] = dict(parsed["gain"])
        controls = module.facecam_controls(parsed)
        self.assertNotIn("led1_mode", controls)
        self.assertIn("privacy", controls)
        self.assertNotIn("privacy", sum((group["controls"] for group in module.facecam_groups(controls)), []))

    def test_a_zero_to_one_integer_is_shown_as_a_toggle(self):
        controls = neo_controls()
        self.assertEqual("toggle", controls["backlight_compensation"]["kind"])
        self.assertEqual("toggle", controls["white_balance_automatic"]["kind"])
        self.assertEqual("range", controls["gain"]["kind"])
        self.assertEqual("choice", controls["power_line_frequency"]["kind"])

    def test_menu_items_get_short_labels(self):
        controls = neo_controls()
        self.assertEqual(["Manual", "Auto"], [item["label"] for item in controls["auto_exposure"]["menu"]])
        self.assertEqual(["Off", "50 Hz", "60 Hz"], [item["label"] for item in controls["power_line_frequency"]["menu"]])

    def test_units_convert_raw_values_for_display(self):
        controls = neo_controls()
        self.assertEqual((0.1, " ms"), (controls["exposure_time_absolute"]["scale"], controls["exposure_time_absolute"]["unit"]))
        self.assertEqual((0.01, "×"), (controls["zoom_absolute"]["scale"], controls["zoom_absolute"]["unit"]))
        self.assertEqual("°", controls["pan_absolute"]["unit"])

    def test_exposure_time_slides_on_a_logarithmic_scale(self):
        """0.1-250 ms on a straight scale squeezes the useful 1-40 ms into the first sixth."""
        controls = neo_controls()
        self.assertEqual("log", controls["exposure_time_absolute"]["curve"])
        self.assertEqual("linear", controls["gain"]["curve"])

    def test_inactive_manual_controls_are_marked(self):
        controls = neo_controls()
        self.assertTrue(controls["white_balance_temperature"]["inactive"])
        self.assertFalse(controls["exposure_time_absolute"]["inactive"])


def fake_sysfs(root, devices):
    """Build /sys/class/video4linux and the USB interfaces it links to.

    `devices` maps a video node name to (vendor, product id, product, index,
    streaming alternate setting).
    """
    video = root / "video4linux"; video.mkdir()
    for number, (node, (vendor, product_id, product, index, alt)) in enumerate(devices.items()):
        usb = root / "usb" / ("3-2.%d" % (number + 1)); usb.mkdir(parents=True)
        for name, value in (("idVendor", "%04x" % vendor), ("idProduct", "%04x" % product_id),
                            ("product", product), ("serial", "SERIAL%d" % number), ("devnum", str(17 + number))):
            (usb / name).write_text(value + "\n")
        for interface, subclass, setting in ((usb.name + ":1.0", "01", 0), (usb.name + ":1.1", "02", alt)):
            path = usb / interface; path.mkdir()
            (path / "bInterfaceClass").write_text("0e\n")
            (path / "bInterfaceSubClass").write_text(subclass + "\n")
            (path / "bAlternateSetting").write_text("%2d\n" % setting)
        entry = video / node; entry.mkdir()
        (entry / "index").write_text("%d\n" % index)
        (entry / "device").symlink_to(usb / (usb.name + ":1.0"))
    return video


class DiscoveryTests(unittest.TestCase):
    def sysfs(self, devices):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        video = fake_sysfs(pathlib.Path(directory.name), devices)
        patcher = mock.patch.object(module, "VIDEO_SYSFS", video); patcher.start(); self.addCleanup(patcher.stop)

    def test_facecam_capture_node_is_found(self):
        self.sysfs({"video2": (0x0FD9, 0x0081, "Elgato Facecam Neo", 0, 0),
                    "video3": (0x0FD9, 0x0081, "Elgato Facecam Neo", 1, 0)})
        cameras = module.discover_facecams()
        self.assertEqual(["/dev/video2"], [camera["device"] for camera in cameras])
        self.assertEqual(("Elgato Facecam Neo", "Facecam Neo", 0x0081, "SERIAL0"),
                         (cameras[0]["product"], cameras[0]["label"], cameras[0]["productId"], cameras[0]["serial"]))

    def test_other_cameras_are_ignored(self):
        self.sysfs({"video0": (0x046D, 0x085E, "Logitech BRIO", 0, 0),
                    "video4": (0x0FD9, 0x0066, "Cam Link 4K", 0, 0)})
        self.assertEqual([], module.discover_facecams())

    def test_nodes_sort_numerically(self):
        self.sysfs({"video10": (0x0FD9, 0x0081, "Elgato Facecam Neo", 0, 0),
                    "video2": (0x0FD9, 0x0078, "Elgato Facecam", 0, 0)})
        self.assertEqual(["/dev/video2", "/dev/video10"], [camera["device"] for camera in module.discover_facecams()])

    def test_streaming_reads_the_video_streaming_interface(self):
        self.sysfs({"video2": (0x0FD9, 0x0081, "Elgato Facecam Neo", 0, 11)})
        self.assertTrue(module.camera_streaming(module.discover_facecams()[0]))

    def test_idle_camera_is_not_streaming(self):
        self.sysfs({"video2": (0x0FD9, 0x0081, "Elgato Facecam Neo", 0, 0)})
        self.assertFalse(module.camera_streaming(module.discover_facecams()[0]))


def fake_proc(root, holders):
    """`holders` maps a pid to (argv0, comm, [fd targets]). An argv0 given as
    bytes is the whole command line, as a process that rewrote its title has."""
    for pid, (argv0, comm, targets) in holders.items():
        entry = root / str(pid); (entry / "fd").mkdir(parents=True)
        (entry / "cmdline").write_bytes(argv0 if isinstance(argv0, bytes) else argv0.encode() + b"\0--type=utility\0")
        (entry / "comm").write_text(comm + "\n")
        for fd, target in enumerate(targets):
            (entry / "fd" / str(fd)).symlink_to(target)
    (root / "self").mkdir()
    return root


class CameraUserTests(unittest.TestCase):
    def proc(self, holders):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = fake_proc(pathlib.Path(directory.name), holders)
        patcher = mock.patch.object(module, "PROC", root); patcher.start(); self.addCleanup(patcher.stop)

    def test_processes_holding_the_node_are_named_after_their_program(self):
        self.proc({300: ("/opt/google/chrome/chrome", "chrome", ["/dev/null", "/dev/video2"]),
                   301: ("/usr/bin/foot", "foot", ["/dev/pts/1"])})
        self.assertEqual({300: "Chrome"}, module.camera_users("/dev/video2"))

    def test_a_rewritten_process_title_is_named_after_its_first_word(self):
        """Chrome rewrites its utility processes' titles into one space-separated string."""
        self.proc({300: (b"/opt/google/chrome/chrome --type=utility --gpu=/dev/dri/renderD128\0\0\0", "chrome", ["/dev/video2"])})
        self.assertEqual({300: "Chrome"}, module.camera_users("/dev/video2"))

    def test_a_program_path_with_spaces_keeps_its_name(self):
        self.proc({300: ("/opt/Some App/some-app", "some-app", ["/dev/video2"])})
        self.assertEqual({300: "Some-app"}, module.camera_users("/dev/video2"))

    def test_the_scan_can_be_limited_to_known_holders(self):
        self.proc({300: ("/opt/google/chrome/chrome", "chrome", ["/dev/video2"]),
                   301: ("/usr/bin/obs", "obs", ["/dev/video2"])})
        self.assertEqual({301: "Obs"}, module.camera_users("/dev/video2", pids=[301, 302]))

    def test_v4l2_ctl_queries_are_not_users(self):
        self.proc({400: ("v4l2-ctl", "v4l2-ctl", ["/dev/video2"])})
        self.assertEqual({}, module.camera_users("/dev/video2"))

    def presence(self, streaming, users, shell=900):
        with mock.patch.object(module, "camera_streaming", return_value=streaming), \
             mock.patch.object(module, "camera_users", return_value=users), \
             mock.patch.object(module.os, "getppid", return_value=shell):
            return module.facecam_presence({"device": "/dev/video2"})

    def test_another_app_streaming_is_live(self):
        state = self.presence(True, {300: "Chrome"})
        self.assertEqual((True, False, ["Chrome"]), (state["live"], state["preview"], state["apps"]))

    def test_the_shell_preview_alone_is_not_live(self):
        state = self.presence(True, {900: "Quickshell"})
        self.assertEqual((False, True, []), (state["live"], state["preview"], state["apps"]))

    def test_a_quickshell_preview_is_not_live_when_the_daemon_runs_elsewhere(self):
        """Run from a terminal or systemd, the daemon's parent is not the shell."""
        state = self.presence(True, {900: "Quickshell"}, shell=42)
        self.assertEqual((False, True), (state["live"], state["preview"]))

    def test_holders_are_reported_for_the_cache_to_check(self):
        self.assertEqual([300, 900], self.presence(True, {300: "Chrome", 900: "Quickshell"})["holders"])

    def test_streaming_with_unknown_holders_is_live(self):
        state = self.presence(True, {})
        self.assertTrue(state["live"])

    def test_an_open_but_idle_camera_is_not_live(self):
        state = self.presence(False, {300: "Chrome"})
        self.assertEqual((False, False), (state["live"], state["preview"]))


def neo_camera(**values):
    """A detected Facecam Neo whose controls hold `values` over the fixture's."""
    controls = neo_controls()
    for name, value in values.items(): controls[name]["value"] = value
    return {"device": "/dev/video2", "product": "Elgato Facecam Neo", "label": "Facecam Neo", "serial": "SERIAL0",
            "devnum": "17", "usb": "/sys/bus/usb/devices/3-2.1", "controls": controls}


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class WritePlanTests(unittest.TestCase):
    def test_automatic_mode_is_written_before_its_manual_value(self):
        plan = module.facecam_write_plan(neo_controls(), {"exposure_time_absolute": 50, "auto_exposure": 1})
        self.assertEqual([[("auto_exposure", 1)], [("exposure_time_absolute", 50)]], plan)

    def test_manual_value_is_skipped_while_its_automatic_mode_is_on(self):
        plan = module.facecam_write_plan(neo_controls(), {"auto_exposure": 3, "exposure_time_absolute": 50})
        self.assertEqual([[("auto_exposure", 3)]], plan)

    def test_current_automatic_mode_decides_when_the_write_leaves_it_alone(self):
        controls = neo_controls()  # white balance is automatic, focus is manual
        self.assertEqual([], module.facecam_write_plan(controls, {"white_balance_temperature": 4000}))
        self.assertEqual([[("focus_absolute", 300)]], module.facecam_write_plan(controls, {"focus_absolute": 300}))

    def test_unknown_and_read_only_controls_are_not_written(self):
        controls = neo_controls(); controls["gain"]["readOnly"] = True
        self.assertEqual([[("contrast", 70)]], module.facecam_write_plan(controls, {"gain": 5, "led1_mode": 1, "contrast": 70}))

    def test_writes_follow_the_inspector_order(self):
        plan = module.facecam_write_plan(neo_controls(), {"sharpness": 1, "brightness": 2, "gain": 3})
        self.assertEqual([[("gain", 3), ("brightness", 2), ("sharpness", 1)]], plan)


class WriteTests(unittest.TestCase):
    def test_controls_are_written_with_v4l2_ctl_without_a_shell(self):
        with mock.patch.object(module.subprocess, "run", return_value=Completed()) as run:
            module.write_facecam_controls(neo_camera(), {"auto_exposure": 1, "exposure_time_absolute": 50, "gain": 4})
        self.assertEqual([["v4l2-ctl", "-d", "/dev/video2", "-c", "auto_exposure=1"],
                          ["v4l2-ctl", "-d", "/dev/video2", "-c", "exposure_time_absolute=50,gain=4"]],
                         [call.args[0] for call in run.call_args_list])
        self.assertTrue(all("shell" not in call.kwargs for call in run.call_args_list))

    def test_a_failed_batch_is_retried_per_control_and_the_failure_is_reported(self):
        results = [Completed(1, stderr="VIDIOC_S_EXT_CTRLS: failed: Input/output error"),
                   Completed(), Completed(1, stderr="VIDIOC_S_EXT_CTRLS: failed: Input/output error")]
        with mock.patch.object(module.subprocess, "run", side_effect=results) as run:
            with self.assertRaisesRegex(RuntimeError, "sharpness"):
                module.write_facecam_controls(neo_camera(), {"brightness": 5, "sharpness": 9})
        self.assertEqual(["brightness=5,sharpness=9", "brightness=5", "sharpness=9"],
                         [call.args[0][-1] for call in run.call_args_list])

    def test_nothing_is_run_for_an_empty_write(self):
        with mock.patch.object(module.subprocess, "run") as run:
            module.write_facecam_controls(neo_camera(), {})
        run.assert_not_called()


class ValueTests(unittest.TestCase):
    def test_range_values_are_clamped_and_snapped_to_the_step(self):
        controls = neo_controls()
        self.assertEqual(7500, module.facecam_value(controls, "white_balance_temperature", 9000))
        self.assertEqual(3710, module.facecam_value(controls, "white_balance_temperature", 3706))
        self.assertEqual(-30, module.facecam_value(controls, "brightness", -99))

    def test_choices_and_toggles_accept_only_their_values(self):
        controls = neo_controls()
        self.assertEqual(3, module.facecam_value(controls, "auto_exposure", 3))
        for name, value in (("auto_exposure", 2), ("white_balance_automatic", 2), ("backlight_compensation", -1)):
            with self.assertRaises(ValueError): module.facecam_value(controls, name, value)

    def test_unknown_and_read_only_controls_are_refused(self):
        controls = neo_controls(); controls["gain"]["readOnly"] = True
        for name in ("gain", "led1_mode", "privacy_"):
            with self.assertRaises(ValueError): module.facecam_value(controls, name, 1)


class ActionTests(unittest.TestCase):
    def test_privacy_toggles(self):
        self.assertEqual({"privacy": 1}, module.facecam_action_values(neo_camera(), "facecam_privacy"))
        self.assertEqual({"privacy": 0}, module.facecam_action_values(neo_camera(privacy=1), "facecam_privacy"))

    def test_zoom_steps_a_quarter_and_stops_at_the_range(self):
        self.assertEqual({"zoom_absolute": 125}, module.facecam_action_values(neo_camera(), "facecam_zoom_in"))
        self.assertEqual({"zoom_absolute": 400}, module.facecam_action_values(neo_camera(zoom_absolute=390), "facecam_zoom_in"))
        self.assertEqual({"zoom_absolute": 100}, module.facecam_action_values(neo_camera(zoom_absolute=110), "facecam_zoom_out"))

    def test_autofocus_toggles(self):
        self.assertEqual({"focus_automatic_continuous": 1}, module.facecam_action_values(neo_camera(), "facecam_autofocus"))

    def test_reset_returns_every_setting_but_privacy_to_its_default(self):
        values = module.facecam_action_values(neo_camera(privacy=1), "facecam_reset")
        self.assertNotIn("privacy", values)
        self.assertEqual((3, 156, 1, 64), (values["auto_exposure"], values["exposure_time_absolute"],
                                           values["white_balance_automatic"], values["saturation"]))

    def test_a_camera_without_the_control_refuses_the_action(self):
        camera = neo_camera(); del camera["controls"]["zoom_absolute"]
        with self.assertRaisesRegex(RuntimeError, "zoom"):
            module.facecam_action_values(camera, "facecam_zoom_in")

    def test_a_disconnected_camera_refuses_actions(self):
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            module.facecam_action_values(None, "facecam_privacy")


class ProfileCase(unittest.TestCase):
    """Runs against a throwaway profile and state directory."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        self.profile_path = root / "profile.json"
        self.profile_path.write_text(json.dumps({"keys": []}))
        for name, value in (("CONFIG", root), ("PROFILE", self.profile_path), ("STATE", root / "state"),
                            ("FACECAM_STATE", root / "state" / "facecam.json")):
            patcher = mock.patch.object(module, name, value); patcher.start(); self.addCleanup(patcher.stop)
        run = mock.patch.object(module.subprocess, "run", return_value=Completed()); self.run = run.start(); self.addCleanup(run.stop)

    def profile(self): return json.loads(self.profile_path.read_text())
    def presets(self): return self.profile()["facecam"]["presets"]
    def written(self): return [call.args[0][-1] for call in self.run.call_args_list if "-c" in call.args[0]]


class PresetTests(ProfileCase):
    def test_saving_snapshots_the_picture_settings_and_makes_the_preset_active(self):
        module.save_facecam_preset(neo_camera(gain=12, privacy=1), "Day")
        preset = self.presets()[0]
        self.assertEqual("Day", preset["name"])
        self.assertEqual(12, preset["controls"]["gain"])
        self.assertNotIn("privacy", preset["controls"])
        self.assertEqual(set(module.FACECAM_CONTROLS), set(preset["controls"]))
        self.assertEqual("Day", module.load_facecam_state()["activePreset"])

    def test_saving_an_existing_name_replaces_it_in_place(self):
        module.save_facecam_preset(neo_camera(gain=1), "Day")
        module.save_facecam_preset(neo_camera(gain=2), "Evening")
        module.save_facecam_preset(neo_camera(gain=3), "  day ")
        self.assertEqual([("day", 3), ("Evening", 2)], [(p["name"], p["controls"]["gain"]) for p in self.presets()])

    def test_preset_names_are_checked(self):
        for name in ("", "   ", "x" * 25, "Day\nNight"):
            with self.assertRaises(ValueError): module.save_facecam_preset(neo_camera(), name)
        self.assertEqual("Late night", module.save_facecam_preset(neo_camera(), " Late   night "))

    def test_applying_writes_the_preset_automatic_modes_first_and_makes_it_active(self):
        module.save_facecam_preset(neo_camera(auto_exposure=1, exposure_time_absolute=40), "Evening")
        self.run.reset_mock()
        module.perform_facecam_action(neo_camera(auto_exposure=3), "facecam_preset:Evening")
        self.assertTrue(self.written()[0].startswith("auto_exposure=1"))
        self.assertIn("exposure_time_absolute=40", self.written()[1])
        self.assertEqual("Evening", module.load_facecam_state()["activePreset"])

    def test_hand_edited_preset_values_are_checked(self):
        self.profile_path.write_text(json.dumps({"facecam": {"presets": [
            {"name": "Odd", "controls": {"gain": "12; rm -rf", "contrast": 70, "led1_mode": 1, "brightness": 999}}]}}))
        module.perform_facecam_action(neo_camera(), "facecam_preset:Odd")
        self.assertEqual(["brightness=30,contrast=70"], self.written())

    def test_an_unknown_preset_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "preset"):
            module.perform_facecam_action(neo_camera(), "facecam_preset:Missing")

    def test_next_preset_cycles_from_the_active_one_and_wraps(self):
        for name in ("A", "B", "C"): module.save_facecam_preset(neo_camera(), name)
        module.perform_facecam_action(neo_camera(), "facecam_preset_next")
        self.assertEqual("A", module.load_facecam_state()["activePreset"])
        module.perform_facecam_action(neo_camera(), "facecam_preset_next")
        self.assertEqual("B", module.load_facecam_state()["activePreset"])

    def test_next_preset_without_presets_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "preset"):
            module.perform_facecam_action(neo_camera(), "facecam_preset_next")

    def test_deleting_the_active_preset_clears_it(self):
        module.save_facecam_preset(neo_camera(), "Day")
        module.delete_facecam_preset("DAY")
        self.assertEqual([], self.presets())
        self.assertIsNone(module.load_facecam_state().get("activePreset"))

    def test_changing_the_picture_leaves_the_active_preset(self):
        module.save_facecam_preset(neo_camera(), "Day")
        module.set_facecam_control(neo_camera(), "gain", 5)
        self.assertIsNone(module.load_facecam_state().get("activePreset"))
        self.assertEqual(["gain=5"], self.written())

    def test_privacy_keeps_the_active_preset(self):
        module.save_facecam_preset(neo_camera(), "Day")
        module.perform_facecam_action(neo_camera(), "facecam_privacy")
        self.assertEqual("Day", module.load_facecam_state()["activePreset"])

    def test_every_change_is_stamped_for_the_daemon(self):
        module.set_facecam_control(neo_camera(), "gain", 5)
        first = module.load_facecam_state()["changedAt"]
        with mock.patch.object(module.time, "time", return_value=first + 5):
            module.perform_facecam_action(neo_camera(), "facecam_privacy")
        self.assertEqual(first + 5, module.load_facecam_state()["changedAt"])


class CatalogTests(ProfileCase):
    def setUp(self):
        super().setUp()
        # The catalog resolves an icon for every installed application.
        patcher = mock.patch.object(module, "desktop_applications", return_value=[]); patcher.start(); self.addCleanup(patcher.stop)

    def test_builtin_facecam_functions_are_in_the_catalog(self):
        values = [option["value"] for option in module.action_catalog()]
        for action in ("facecam_privacy", "facecam_zoom_in", "facecam_zoom_out", "facecam_autofocus",
                       "facecam_reset", "facecam_preset_next"):
            self.assertIn(action, values)

    def test_saved_presets_become_functions(self):
        module.save_facecam_preset(neo_camera(), "Day")
        option = next(o for o in module.action_catalog() if o["value"] == "facecam_preset:Day")
        self.assertEqual("Function · Facecam Preset · Day", option["label"])
        self.assertTrue(module.valid_action("facecam_preset:Day"))
        self.assertFalse(module.valid_action("facecam_preset:Night"))
        self.assertEqual("Day", module.action_label("facecam_preset:Day"))

    def test_preset_names_cannot_carry_markup_into_the_catalog(self):
        self.profile_path.write_text(json.dumps({"facecam": {"presets": [{"name": "<b>x</b>", "controls": {}}]}}))
        self.assertNotIn("<b>", json.dumps(module.action_catalog()))


class RecordTests(ProfileCase):
    def test_record_describes_the_camera_for_the_panel(self):
        self.run.return_value = Completed(stdout=FACECAM_NEO_CONTROLS)
        camera = {key: value for key, value in neo_camera().items() if key != "controls"}
        with mock.patch.object(module, "facecam_presence", return_value={"streaming": False, "live": False, "preview": False, "apps": []}):
            record = module.facecam_record(camera)
        self.assertEqual(("camera", True, False), (record["kind"], record["connected"], record["privacy"]))
        self.assertEqual(["exposure", "color", "lens", "image"], [group["id"] for group in record["groups"]])
        self.assertIn("gain", record["controls"])
        self.assertIsNone(record["activePreset"])
        self.assertGreater(record["controlsReadAt"], 0)
        self.assertEqual(["v4l2-ctl", "-d", "/dev/video2", "--list-ctrls-menus"], self.run.call_args.args[0])

    def test_an_unreadable_camera_keeps_its_record_with_the_error(self):
        self.run.return_value = Completed(1, stderr="Cannot open device /dev/video2")
        with mock.patch.object(module, "facecam_presence", return_value={"streaming": False, "live": False, "preview": False, "apps": []}):
            record = module.facecam_record({"device": "/dev/video2", "product": "Elgato Facecam Neo"})
        self.assertEqual({}, record["controls"])
        self.assertIn("Cannot open", record["error"])


class FakeHid:
    def __init__(self): self.features, self.writes = [], []
    def feature(self, dev, values): self.features.append(values)
    def write(self, dev, values): self.writes.append(values)


IDLE = {"streaming": False, "live": False, "preview": False, "apps": []}


class DaemonTests(ProfileCase):
    def setUp(self):
        super().setUp()
        self.daemon = module.Daemon.__new__(module.Daemon)
        self.daemon.hid, self.daemon.previous = FakeHid(), {}
        self.daemon.profile = {"keys": [{"label": "Privacy", "action": "facecam_privacy"}]}
        self.daemon.status, self.daemon.devices, self.daemon.light_states = {}, {}, []
        self.daemon.brightness = 55
        self.camera = {key: value for key, value in neo_camera().items() if key != "controls"}
        self.reads = []
        def record(camera, presence=None):
            self.reads.append(camera["device"])
            return dict(neo_camera(**self.values), **(presence or IDLE), kind="camera", privacy=bool(self.values.get("privacy")))
        self.values = {}
        for name, value in (("discover_facecams", lambda: [dict(self.camera)]), ("facecam_record", record),
                            ("facecam_presence", lambda camera: dict(IDLE))):
            patcher = mock.patch.object(module, name, side_effect=value); patcher.start(); self.addCleanup(patcher.stop)
        self.clock = 1000.0
        patcher = mock.patch.object(module.time, "monotonic", side_effect=lambda: self.clock); patcher.start(); self.addCleanup(patcher.stop)

    def test_controls_are_read_on_connect_and_then_every_ten_seconds(self):
        self.daemon.refresh_facecam(); self.clock += 2; self.daemon.refresh_facecam()
        self.assertEqual(1, len(self.reads))
        self.clock += 9; self.daemon.refresh_facecam()
        self.assertEqual(2, len(self.reads))
        self.assertEqual("/dev/video2", self.daemon.status["facecam"]["device"])

    def test_a_change_stamped_by_the_panel_is_read_at_once(self):
        self.daemon.refresh_facecam()
        module.save_facecam_state(activePreset=None)
        self.daemon.refresh_facecam()
        self.assertEqual(2, len(self.reads))

    def test_a_disconnected_camera_clears_its_status(self):
        self.daemon.refresh_facecam()
        module.discover_facecams.side_effect = lambda: []
        self.daemon.refresh_facecam()
        self.assertIsNone(self.daemon.status["facecam"])

    def test_a_connected_camera_gets_its_active_preset_back(self):
        module.save_facecam_preset(neo_camera(), "Day")
        self.daemon.profile = module.load_profile()
        with mock.patch.object(module, "apply_facecam_preset") as apply:
            self.daemon.refresh_facecam(); self.daemon.refresh_facecam()
            self.assertEqual(1, apply.call_count)
            self.assertEqual("Day", apply.call_args.args[1])
            self.camera["devnum"] = "18"  # unplugged and plugged back between polls
            self.daemon.refresh_facecam()
            self.assertEqual(2, apply.call_count)

    def test_the_preset_is_restored_once_the_camera_can_be_read(self):
        """Just after plug-in the node may not be readable yet (udev has not set its ACL)."""
        module.save_facecam_preset(neo_camera(), "Day")
        self.daemon.profile = module.load_profile()
        readable = [False]
        def record(camera, presence=None):
            self.reads.append(camera["device"])
            return dict(neo_camera() if readable[0] else dict(camera, controls={}), **(presence or IDLE), kind="camera", privacy=False)
        module.facecam_record.side_effect = record
        with mock.patch.object(module, "apply_facecam_preset") as apply:
            self.daemon.refresh_facecam()
            apply.assert_not_called()
            readable[0] = True; self.clock += 11; self.daemon.refresh_facecam()
            self.clock += 11; self.daemon.refresh_facecam()
        self.assertEqual(1, apply.call_count)

    def test_no_preset_is_applied_without_an_active_one(self):
        module.save_facecam_preset(neo_camera(), "Day"); module.save_facecam_state(activePreset=None)
        with mock.patch.object(module, "apply_facecam_preset") as apply:
            self.daemon.refresh_facecam()
        apply.assert_not_called()

    def test_a_deleted_active_preset_is_not_applied(self):
        module.save_facecam_state(activePreset="Gone")
        with mock.patch.object(module, "apply_facecam_preset") as apply:
            self.daemon.refresh_facecam()
        apply.assert_not_called()
        self.assertFalse(self.daemon.status.get("error"))

    def test_privacy_changes_redraw_the_keys(self):
        self.daemon.refresh_facecam()
        with mock.patch.object(module.Daemon, "redraw_decks") as redraw:
            self.values["privacy"] = 1; self.clock += 11; self.daemon.refresh_facecam()
            self.clock += 11; self.daemon.refresh_facecam()
        self.assertEqual(1, redraw.call_count)

    def test_unplugging_a_private_camera_redraws_the_keys(self):
        self.values["privacy"] = 1
        with mock.patch.object(module.Daemon, "redraw_decks") as redraw:
            self.daemon.refresh_facecam()
            module.discover_facecams.side_effect = lambda: []
            self.daemon.refresh_facecam()
        self.assertEqual(2, redraw.call_count)

    def test_privacy_key_shows_the_privacy_state(self):
        self.daemon.status["facecam"] = {"privacy": True}
        self.assertEqual("facecam_privacy_on", self.daemon.key_artwork("facecam_privacy"))
        self.daemon.status["facecam"] = {"privacy": False}
        self.assertEqual("facecam_privacy", self.daemon.key_artwork("facecam_privacy"))
        self.assertEqual("lock", self.daemon.key_artwork("lock"))

    def test_facecam_functions_run_on_the_detected_camera(self):
        self.daemon.refresh_facecam()
        with mock.patch.object(module, "perform_facecam_action") as perform:
            self.daemon.act("facecam_zoom_in")
        self.assertEqual("/dev/video2", perform.call_args.args[0]["device"])
        self.assertEqual("facecam_zoom_in", perform.call_args.args[1])
        # Connect, then before and after the function.
        self.assertEqual(3, len(self.reads))

    def test_key_functions_start_from_a_fresh_reading(self):
        """Another app may have changed the camera since the last poll."""
        self.daemon.refresh_facecam()
        self.values["zoom_absolute"] = 300  # changed behind the daemon's back
        with mock.patch.object(module, "perform_facecam_action") as perform:
            self.daemon.act("facecam_zoom_in")
        self.assertEqual(300, perform.call_args.args[0]["controls"]["zoom_absolute"]["value"])

    def test_a_failed_facecam_function_is_reported(self):
        with mock.patch.object(module, "perform_facecam_action", side_effect=RuntimeError("Facecam is not connected")):
            self.daemon.act("facecam_privacy")
        self.assertEqual("Facecam: Facecam is not connected", self.daemon.status["error"])


class PresenceCacheTests(unittest.TestCase):
    def test_the_process_scan_runs_when_streaming_starts_and_then_every_thirty_seconds(self):
        daemon = module.Daemon.__new__(module.Daemon)
        clock = [1000.0]; streaming = [False]; scans = []
        camera = {"device": "/dev/video2"}
        def users(device, pids=None):
            if pids is None: scans.append(clock[0])
            return {300: "Chrome"}
        with mock.patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(module, "camera_streaming", side_effect=lambda c: streaming[0]), \
             mock.patch.object(module, "camera_users", side_effect=users):
            daemon.facecam_state(camera)
            streaming[0] = True; clock[0] += 2; daemon.facecam_state(camera)
            clock[0] += 2; state = daemon.facecam_state(camera)
            self.assertEqual(1, len(scans))
            self.assertEqual(["Chrome"], state["apps"])
            clock[0] += 20; daemon.facecam_state(camera)
            self.assertEqual(1, len(scans))
            clock[0] += 9; daemon.facecam_state(camera)
            self.assertEqual(2, len(scans))


class CommandTests(ProfileCase):
    def setUp(self):
        super().setUp()
        self.detections = []
        def detect(presence=True):
            self.detections.append(presence)
            return neo_camera()
        patcher = mock.patch.object(module, "detect_facecam", side_effect=detect); patcher.start(); self.addCleanup(patcher.stop)

    def test_set_writes_a_whole_number_and_returns_the_camera(self):
        with mock.patch.object(module, "set_facecam_control") as set_control:
            camera = module.facecam_command("set", ["gain", "12"])
        self.assertEqual(("gain", 12), set_control.call_args.args[1:])
        self.assertEqual("/dev/video2", camera["device"])

    def test_changes_skip_the_process_scan(self):
        with mock.patch.object(module, "perform_facecam_action"):
            module.facecam_command("zoom-in", [])
        self.assertEqual([False, False], self.detections)

    def test_status_includes_who_is_streaming(self):
        module.facecam_command("status", [])
        self.assertEqual([True], self.detections)

    def test_functions_map_to_their_actions(self):
        with mock.patch.object(module, "perform_facecam_action") as perform:
            for command, action in (("privacy", "facecam_privacy"), ("zoom-out", "facecam_zoom_out"),
                                    ("autofocus", "facecam_autofocus"), ("reset", "facecam_reset"),
                                    ("next-preset", "facecam_preset_next")):
                module.facecam_command(command, [])
                self.assertEqual(action, perform.call_args.args[1])
            module.facecam_command("apply-preset", ["Day"])
            self.assertEqual("facecam_preset:Day", perform.call_args.args[1])

    def test_argument_counts_and_numbers_are_checked(self):
        for command, arguments in (("set", ["gain"]), ("set", ["gain", "loud"]), ("privacy", ["on"]),
                                   ("save-preset", []), ("status", ["x"])):
            with self.assertRaises(ValueError): module.facecam_command(command, arguments)

    def test_presets_are_deleted_without_reading_the_camera(self):
        module.save_facecam_preset(neo_camera(), "Day"); self.detections.clear()
        module.facecam_command("delete-preset", ["Day"])
        self.assertEqual([], self.presets())
        self.assertEqual([False], self.detections)


class ArtworkTests(unittest.TestCase):
    def test_every_facecam_function_and_the_privacy_on_state_have_artwork(self):
        for action in ("facecam_privacy", "facecam_privacy_on", "facecam_zoom_in", "facecam_zoom_out",
                       "facecam_autofocus", "facecam_reset", "facecam_preset_next"):
            self.assertTrue((module.ICONS / (action + ".jpg")).is_file(), action)

    def test_named_presets_draw_the_preset_glyph_over_their_name(self):
        self.assertFalse((module.ICONS / "facecam_preset:Day.jpg").is_file())
        self.assertTrue(module.action_icon("facecam_preset:Day").endswith("facecam_preset.png"))
        self.assertTrue(pathlib.Path(module.action_icon("facecam_preset:Day")).is_file())


class PanelTests(unittest.TestCase):
    ROOT = pathlib.Path(__file__).parents[1]

    def text(self, name): return (self.ROOT / name).read_text()

    def test_a_facecam_alone_counts_as_connected_and_has_a_page(self):
        panel = self.text("Panel.qml")
        line = next(x for x in panel.splitlines() if "readonly property bool connected:" in x)
        self.assertIn("hasFacecam", line)
        self.assertIn('hasFacecam ? { value: "facecam"', panel)

    def test_only_the_preview_file_needs_qt_multimedia(self):
        """The panel must still load where Qt Multimedia is not installed."""
        for name in ("Panel.qml", "FacecamStage.qml", "FacecamInspector.qml", "FacecamControl.qml", "BarWidget.qml"):
            self.assertNotIn("QtMultimedia", self.text(name), name)
        self.assertIn("import QtMultimedia", self.text("FacecamPreview.qml"))
        self.assertIn('source: Qt.resolvedUrl("FacecamPreview.qml")', self.text("FacecamStage.qml"))

    def test_status_is_read_from_the_status_file_without_starting_a_process(self):
        panel = self.text("Panel.qml")
        self.assertIn("FileView {", panel)
        self.assertNotIn('[root.helper, "status", "--json"]', panel)

    def test_panel_keys_reach_the_preset_name_field(self):
        self.assertIn("blocked: facecamStage.editing", self.text("Panel.qml"))

    def test_a_drag_keeps_only_the_latest_value_per_control_in_the_queue(self):
        panel = self.text("Panel.qml")
        self.assertIn('queued[0] === "set" && queued[1] === args[1]', panel)

    def test_the_preview_stops_when_the_page_closes(self):
        self.assertIn('shown: root.opened && root.selectedDevice === "facecam"', self.text("Panel.qml"))

    def test_the_bar_icon_marks_a_live_camera(self):
        self.assertIn("facecamLive", self.text("BarWidget.qml"))


class PresenceHandOverTests(unittest.TestCase):
    """The cached answer must not outlive the process it names."""
    def test_a_stream_handed_from_the_preview_to_a_call_is_seen_at_the_next_poll(self):
        daemon = module.Daemon.__new__(module.Daemon)
        clock = [1000.0]; holders = [{900: "Quickshell"}]
        camera = {"device": "/dev/video2"}
        def users(device, pids=None):
            found = holders[0]
            return {pid: name for pid, name in found.items() if pids is None or pid in pids}
        with mock.patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(module, "camera_streaming", return_value=True), \
             mock.patch.object(module, "camera_users", side_effect=users), \
             mock.patch.object(module.os, "getppid", return_value=900):
            self.assertTrue(daemon.facecam_state(camera)["preview"])
            holders[0] = {300: "Chrome"}; clock[0] += 2
            state = daemon.facecam_state(camera)
        self.assertEqual((True, ["Chrome"]), (state["live"], state["apps"]))


if __name__ == "__main__":
    unittest.main()
