# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic parser fixtures and mocked invocation; no Windows image is run."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pe_inspector as pe
import windows_compatibility as compatibility


def make_pe(machine=0x8664, imports=(), delayed=(), clr=False, subsystem=3,
            characteristics=0x22) -> bytearray:
    """A minimal structural fixture, deliberately without executable machine code."""
    is_32 = machine == 0x14C
    optional_size = 224 if is_32 else 240
    optional_start, directories = 0x98, 96 if is_32 else 112
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, machine, 1, 0, 0, 0, optional_size, characteristics)
    struct.pack_into("<H", data, optional_start, 0x10B if is_32 else 0x20B)
    struct.pack_into("<I", data, optional_start + 16, 0x1000)
    struct.pack_into("<I", data, optional_start + 32, 0x1000)
    struct.pack_into("<I", data, optional_start + 36, 0x200)
    struct.pack_into("<I", data, optional_start + 56, 0x2000)
    struct.pack_into("<I", data, optional_start + 60, 0x200)
    struct.pack_into("<H", data, optional_start + 68, subsystem)
    struct.pack_into("<I", data, optional_start + (92 if is_32 else 108), 16)
    if is_32:
        struct.pack_into("<I", data, optional_start + 28, 0x400000)
    else:
        struct.pack_into("<Q", data, optional_start + 24, 0x140000000)
    section = optional_start + optional_size
    data[section:section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x1000, 0x1000, 0x1000, 0x200)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    next_name = 0x500

    def name_address(name):
        nonlocal next_name
        encoded = name.encode("ascii") + b"\0"
        data[next_name:next_name + len(encoded)] = encoded
        rva = next_name - 0x200 + 0x1000
        next_name += len(encoded)
        return rva

    if imports:
        struct.pack_into("<II", data, optional_start + directories + 8,
                         0x1000, (len(imports) + 1) * 20)
        for index, name in enumerate(imports):
            struct.pack_into("<IIIII", data, 0x200 + index * 20, 1, 0, 0, name_address(name), 1)
    if delayed:
        struct.pack_into("<II", data, optional_start + directories + 13 * 8,
                         0x1100, (len(delayed) + 1) * 32)
        for index, name in enumerate(delayed):
            struct.pack_into("<IIIIIIII", data, 0x300 + index * 32,
                             1, name_address(name), 0, 0, 0, 0, 0, 0)
    if clr:
        struct.pack_into("<II", data, optional_start + directories + 14 * 8, 0x1200, 72)
        struct.pack_into("<IHH", data, 0x400, 72, 2, 5)
        struct.pack_into("<I", data, 0x410, 1)
    return data


def macho(cpu=compatibility.CPU_X86_64, file_type=2) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<IIIIIII", cpu, 3, file_type, 0, 0, 0, 0)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.image = self.root / "fixture.exe"
        self.image.write_bytes(make_pe())
        self.wine = self.root / "selected-wine"
        self.wine.write_bytes(macho())
        self.wine.chmod(0o755)
        self.prefix = self.root / "dedicated-prefix"

    def tearDown(self):
        self.directory.cleanup()

    def inspect(self, data=None):
        if data is not None:
            self.image.write_bytes(data)
        return pe.inspect_pe(self.image)

    def assert_rejected(self, data, code):
        with self.assertRaises(pe.InspectionError) as raised:
            self.inspect(data)
        self.assertEqual(raised.exception.code, code)

    @contextlib.contextmanager
    def intel_mac(self):
        with mock.patch.object(compatibility.platform, "system", return_value="Darwin"), \
             mock.patch.object(compatibility.platform, "machine", return_value="x86_64"):
            yield

    def fake_wine(self, version=b"wine-11.0\n", exit_code=0):
        def run(argv, **kwargs):
            if argv[-1] == "--version":
                kwargs["stdout"].write(version)
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=exit_code)
        return run

    def test_x64_metadata_has_no_execution_or_path(self):
        report = self.inspect()
        self.assertEqual(report["architecture"], "x86_64")
        self.assertFalse(report["executed"])
        self.assertFalse(report["signature_verified"])
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertEqual(report["launch_blockers"], [])

    def test_x86_requires_wow64(self):
        report = self.inspect(make_pe(machine=0x14C))
        self.assertEqual(report["format"], "PE32")
        self.assertTrue(report["requires_wow64"])

    def test_standard_imports_and_graphics_hints(self):
        report = self.inspect(make_pe(imports=("KERNEL32.dll", "D3D11.dll", "VCRUNTIME140.dll")))
        self.assertEqual(report["graphics_imports"], ["d3d11.dll"])
        self.assertIn("visual_cpp_2015_or_later_candidate", report["runtime_hints"])
        self.assertFalse(report["import_analysis_complete"])

    def test_delay_imports_are_inspected(self):
        report = self.inspect(make_pe(delayed=("dxgi.dll", "hostfxr.dll")))
        self.assertEqual(report["delay_imports"], ["dxgi.dll", "hostfxr.dll"])
        self.assertIn("dotnet_runtime_candidate", report["runtime_hints"])

    def test_clr_hint_does_not_claim_framework_version(self):
        report = self.inspect(make_pe(clr=True))
        self.assertTrue(report["managed_clr"])
        self.assertIn("managed_runtime_family_unverified", report["runtime_hints"])
        self.assertNotIn("framework_version", report)

    def test_truncated_file_rejected(self):
        self.assert_rejected(b"MZ", "file_range")

    def test_wrong_signatures_rejected(self):
        data = make_pe()
        data[:2] = b"AB"
        self.assert_rejected(data, "dos_signature")
        data = make_pe()
        data[0x80:0x84] = b"NE\0\0"
        self.assert_rejected(data, "pe_signature")

    def test_header_offset_outside_file_rejected(self):
        data = make_pe()
        struct.pack_into("<I", data, 60, 0xFFFFFFF0)
        self.assert_rejected(data, "file_range")

    def test_machine_and_optional_header_mismatch_rejected(self):
        data = make_pe()
        struct.pack_into("<H", data, 0x84, 0x14C)
        self.assert_rejected(data, "machine_header_mismatch")

    def test_directory_count_cannot_escape_optional_header(self):
        data = make_pe()
        struct.pack_into("<I", data, 0x98 + 108, 17)
        self.assert_rejected(data, "directory_limits")

    def test_section_raw_range_rejected(self):
        data = make_pe()
        struct.pack_into("<I", data, 0x98 + 240 + 20, 0x1200)
        self.assert_rejected(data, "section_file_range")

    def test_overlap_is_not_guessed(self):
        data = make_pe()
        struct.pack_into("<H", data, 0x86, 2)
        section = 0x98 + 240
        data[section + 40:section + 80] = data[section:section + 40]
        self.assert_rejected(data, "ambiguous_sections")

    def test_import_rva_cannot_point_into_virtual_zero_fill(self):
        data = make_pe(imports=("kernel32.dll",))
        struct.pack_into("<I", data, 0x98 + 240 + 16, 0x800)
        struct.pack_into("<I", data, 0x20C, 0x1FFF)
        self.assert_rejected(data, "rva_not_file_backed")

    def test_import_name_paths_are_rejected(self):
        self.assert_rejected(make_pe(imports=("C:\\private\\secret.dll",)), "import_name_format")

    def test_import_name_requires_termination(self):
        data = make_pe(imports=("kernel32.dll",))
        data[0x500:0x601] = b"A" * 257
        self.assert_rejected(data, "import_name_termination")

    def test_import_table_requires_termination(self):
        data = make_pe(imports=("kernel32.dll",))
        struct.pack_into("<I", data, 0x98 + 112 + 12, 20)
        self.assert_rejected(data, "import_directory_termination")

    def test_delay_import_attributes_checked(self):
        data = make_pe(delayed=("dxgi.dll",))
        struct.pack_into("<I", data, 0x300, 3)
        self.assert_rejected(data, "delay_import_attributes")

    def test_legacy_delay_import_va_is_converted_for_pe32(self):
        data = make_pe(machine=0x14C, delayed=("dxgi.dll",))
        name_rva = struct.unpack_from("<I", data, 0x304)[0]
        struct.pack_into("<II", data, 0x300, 0, 0x400000 + name_rva)
        self.assertEqual(self.inspect(data)["delay_imports"], ["dxgi.dll"])

    def test_clr_header_size_is_bounded_by_its_directory(self):
        data = make_pe(clr=True)
        struct.pack_into("<I", data, 0x400, 73)
        self.assert_rejected(data, "clr_header_size")

    def test_certificate_is_file_offset_not_rva_and_not_verified(self):
        data = make_pe()
        struct.pack_into("<II", data, 0x98 + 112 + 4 * 8, 0x1100, 16)
        report = self.inspect(data)
        self.assertTrue(report["signature_declared"])
        self.assertFalse(report["signature_verified"])

    def test_certificate_out_of_file_rejected(self):
        data = make_pe()
        struct.pack_into("<II", data, 0x98 + 112 + 4 * 8, 0x11FF, 16)
        self.assert_rejected(data, "certificate_file_range")

    def test_arm_dll_and_kernel_images_are_blocked(self):
        arm = self.inspect(make_pe(machine=0xAA64))
        self.assertIn("unsupported_target_architecture", arm["launch_blockers"])
        dll = self.inspect(make_pe(characteristics=0x2022))
        self.assertIn("dll_is_not_a_program", dll["launch_blockers"])
        driver = self.inspect(make_pe(subsystem=1, characteristics=0x1022))
        self.assertIn("not_windows_userland_gui_or_console", driver["launch_blockers"])

    def test_file_bound_before_metadata_allocation(self):
        with mock.patch.object(pe, "MAX_FILE_BYTES", 100):
            with self.assertRaises(pe.InspectionError) as raised:
                pe.inspect_pe(self.image)
        self.assertEqual(raised.exception.code, "file_type_or_size_limit")

    def test_thin_macho_intel_detected_without_identity_claim(self):
        report = compatibility.inspect_wine(self.wine)
        self.assertTrue(report["intel_executable_slice"])
        self.assertFalse(report["wine_version_report_verified"])
        self.assertFalse(report["wow64_verified"])

    def test_fat_macho_intel_slice_detected(self):
        data = bytearray(256)
        struct.pack_into(">II", data, 0, 0xCAFEBABE, 1)
        struct.pack_into(">IIIII", data, 8, compatibility.CPU_X86_64, 3, 128, 32, 0)
        data[128:160] = macho()
        self.wine.write_bytes(data)
        self.assertTrue(compatibility.inspect_wine(self.wine)["intel_executable_slice"])

    def test_fat64_macho_intel_slice_detected(self):
        data = bytearray(256)
        struct.pack_into(">II", data, 0, 0xCAFEBABF, 1)
        struct.pack_into(">IIQQII", data, 8, compatibility.CPU_X86_64, 3, 128, 32, 0, 0)
        data[128:160] = macho()
        self.wine.write_bytes(data)
        self.assertTrue(compatibility.inspect_wine(self.wine)["intel_executable_slice"])

    def test_runtime_shell_or_windows_file_rejected(self):
        self.wine.write_bytes(b"#!/bin/sh\n" + b"A" * 64)
        with self.assertRaises(pe.InspectionError) as raised:
            compatibility.inspect_wine(self.wine)
        self.assertEqual(raised.exception.code, "wine_runtime_not_macho")

    def test_runtime_fat_range_checked(self):
        data = bytearray(256)
        struct.pack_into(">II", data, 0, 0xCAFEBABE, 1)
        struct.pack_into(">IIIII", data, 8, compatibility.CPU_X86_64, 3, 250, 32, 0)
        self.wine.write_bytes(data)
        with self.assertRaises(pe.InspectionError) as raised:
            compatibility.inspect_wine(self.wine)
        self.assertEqual(raised.exception.code, "wine_runtime_slice_range")

    def test_plan_on_windows_has_blocker_and_never_runs(self):
        with mock.patch.object(compatibility.platform, "system", return_value="Windows"), \
             mock.patch.object(compatibility.subprocess, "run") as run:
            plan = compatibility.make_plan(self.image, self.wine, self.prefix)
            self.assertIn("requires_native_intel_macos", plan.blockers)
            self.assertFalse(plan.report()["executed"])
            self.assertFalse(self.prefix.exists())
            run.assert_not_called()

    def test_plan_report_omits_private_paths_and_arguments(self):
        plan = compatibility.make_plan(self.image, self.wine, self.prefix, ("private-token",))
        data = json.dumps(plan.report())
        self.assertNotIn(str(self.root), data)
        self.assertNotIn("private-token", data)
        self.assertEqual(plan.report()["argument_count"], 1)

    def test_nonempty_unowned_prefix_is_not_adopted(self):
        self.prefix.mkdir()
        (self.prefix / "user.reg").write_text("old", encoding="utf-8")
        with self.assertRaises(pe.InspectionError) as raised:
            compatibility.make_plan(self.image, self.wine, self.prefix)
        self.assertEqual(raised.exception.code, "existing_prefix_not_owned_by_module")
        self.assertEqual((self.prefix / "user.reg").read_text(encoding="utf-8"), "old")

    def test_home_is_not_an_allowed_prefix(self):
        with self.assertRaises(pe.InspectionError) as raised:
            compatibility.make_plan(self.image, self.wine, Path.home())
        self.assertEqual(raised.exception.code, "prefix_must_be_dedicated_directory")

    def test_invalid_marker_not_adopted(self):
        self.prefix.mkdir()
        (self.prefix / compatibility.PREFIX_MARKER).write_text('{"other":1}', encoding="utf-8")
        with self.assertRaises(pe.InspectionError) as raised:
            compatibility.prefix_state(self.prefix)
        self.assertEqual(raised.exception.code, "prefix_marker_invalid")

    def test_arguments_reject_nul_and_size_exhaustion(self):
        for values in (("x\0y",), ("a",) * 65, ("a" * 4097,), ("é" * 4000,) * 5, ("\ud800",)):
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.checked_arguments(values)
            self.assertEqual(raised.exception.code, "argument_limits")

    def test_environment_cannot_inherit_dll_or_dyld_injection(self):
        with mock.patch.dict(os.environ, {"WINEDLLOVERRIDES": "malicious", "WINEPREFIX": "old",
                                         "DYLD_INSERT_LIBRARIES": "secret", "LD_PRELOAD": "secret",
                                         "WINEARCH": "win32", "PATH": "/explicit/path"}, clear=True):
            environment = compatibility.clean_environment(self.prefix)
        self.assertEqual(environment["WINEPREFIX"], str(self.prefix))
        self.assertEqual(environment["PATH"], "/explicit/path")
        self.assertNotIn("WINEDLLOVERRIDES", environment)
        self.assertNotIn("DYLD_INSERT_LIBRARIES", environment)
        self.assertNotIn("LD_PRELOAD", environment)
        self.assertNotIn("WINEARCH", environment)

    def test_launch_on_windows_cannot_execute_even_selected_runtime(self):
        with mock.patch.object(compatibility.platform, "system", return_value="Windows"), \
             mock.patch.object(compatibility.subprocess, "run") as run:
            plan = compatibility.make_plan(self.image, self.wine, self.prefix)
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.execute_plan(plan)
        self.assertEqual(raised.exception.code, "launch_requirements_unmet")
        self.assertFalse(self.prefix.exists())
        run.assert_not_called()

    def test_launch_preserves_metacharacters_as_literal_arguments(self):
        arguments = ("; touch /never", "$(never)", "`never`", "--flag=x y")
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=self.fake_wine()) as run:
            plan = compatibility.make_plan(self.image, self.wine, self.prefix, arguments, "install")
            result = compatibility.execute_plan(plan)
        self.assertEqual(run.call_count, 2)
        actual, kwargs = run.call_args
        self.assertEqual(actual[0], [str(self.wine), str(self.image), *arguments])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(self.prefix))
        self.assertEqual(result["return_code"], 0)
        self.assertFalse(result["installation_verified"])
        self.assertFalse(result["runtime"]["wow64_verified"])
        self.assertEqual(compatibility.prefix_state(self.prefix), "module_prefix")

    def test_nonzero_exit_is_reported_without_success_claim(self):
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=self.fake_wine(exit_code=7)):
            result = compatibility.execute_plan(compatibility.make_plan(self.image, self.wine, self.prefix))
        self.assertEqual(result["return_code"], 7)
        self.assertEqual(result["pe"]["app_compatibility"], "unverified")

    def test_changed_image_after_plan_is_rejected_before_execution(self):
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run") as run:
            plan = compatibility.make_plan(self.image, self.wine, self.prefix)
            data = make_pe()
            data[-1] = 1
            self.image.write_bytes(data)
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.execute_plan(plan)
        self.assertEqual(raised.exception.code, "selected_input_changed")
        self.assertFalse(self.prefix.exists())
        run.assert_not_called()

    def test_x86_older_wine_rejected_without_prefix_mutation(self):
        self.image.write_bytes(make_pe(machine=0x14C))
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=self.fake_wine(version=b"wine-10.0\n")) as run:
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.execute_plan(compatibility.make_plan(self.image, self.wine, self.prefix))
        self.assertEqual(raised.exception.code, "x86_requires_selected_wine_11_or_newer")
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.prefix.exists())

    def test_version_probe_must_identify_wine_and_omit_raw_output(self):
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=self.fake_wine(version=b"private output\n")):
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.probe_runtime(self.wine)
        self.assertEqual(raised.exception.code, "wine_version_probe_failed")
        self.assertNotIn("private output", str(raised.exception))

    def test_version_probe_timeout_has_no_prefix_effect(self):
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=compatibility.subprocess.TimeoutExpired("wine", 5)):
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.probe_runtime(self.wine)
        self.assertEqual(raised.exception.code, "wine_version_probe_failed")
        self.assertFalse(self.prefix.exists())

    def test_version_output_limit_does_not_publish_content(self):
        with self.intel_mac(), mock.patch.object(compatibility.subprocess, "run",
                                               side_effect=self.fake_wine(version=b"A" * 65537)):
            with self.assertRaises(pe.InspectionError) as raised:
                compatibility.probe_runtime(self.wine)
        self.assertEqual(raised.exception.code, "wine_version_output_limit")

    def test_cli_read_error_contains_no_private_filename(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = compatibility.main(["inspect", str(self.root / "private-does-not-exist.exe")])
        self.assertEqual(exit_code, 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report["error"], "selected_file_unreadable")
        self.assertNotIn("private-does-not-exist", output.getvalue())

    def test_cli_plan_is_read_only_with_install_mode(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(compatibility.subprocess, "run") as run:
            exit_code = compatibility.main(["plan", "--mode", "install", str(self.image), "--", "/quiet"])
        self.assertEqual(exit_code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["mode"], "install")
        self.assertEqual(report["argument_count"], 1)
        self.assertFalse(report["executed"])
        run.assert_not_called()

    def test_non_exe_cannot_be_launched_even_with_executable_header(self):
        other = self.root / "fixture.sys"
        other.write_bytes(make_pe())
        with self.intel_mac():
            plan = compatibility.make_plan(other, self.wine, self.prefix)
        self.assertIn("selected_image_is_not_exe", plan.blockers)

    def test_bounded_header_mutations_have_only_structured_outcomes(self):
        generator = random.Random(4026)
        for _ in range(100):
            data = make_pe(imports=("kernel32.dll",), delayed=("dxgi.dll",), clr=True)
            index = generator.randrange(0, 0x428)
            data[index:index + 4] = generator.getrandbits(32).to_bytes(4, "little")
            try:
                report = self.inspect(data)
                self.assertFalse(report["executed"])
                self.assertEqual(report["app_compatibility"], "unverified")
            except pe.InspectionError as exc:
                self.assertIsInstance(exc.code, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
