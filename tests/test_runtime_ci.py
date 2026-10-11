# SPDX-License-Identifier: GPL-3.0-only
"""Portable recipe, integrity, archive and result tests; no runtime is executed."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import wine_runtime_ci as runtime


class Response(io.BytesIO):
    def __init__(self, data, url="https://dl.winehq.org/wine/source/11.0/wine-11.0.tar.xz", length=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def geturl(self):
        return self.url


class RuntimeRecipeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.pins = runtime.load_pins()

    def tearDown(self):
        self.directory.cleanup()

    def error(self, code, operation, *arguments):
        with self.assertRaises(runtime.RuntimeBuildError) as error:
            operation(*arguments)
        self.assertEqual(error.exception.code, code)

    def mutated_pins(self, mutator):
        pins = copy.deepcopy(self.pins)
        mutator(pins)
        path = self.root / "pins.json"
        path.write_text(json.dumps(pins), encoding="utf-8")
        return path

    def download_item(self, data):
        return {"url": self.pins["wine"]["url"], "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}

    def tar_buffer(self, members):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:xz") as archive:
            for name, kind, contents in members:
                member = tarfile.TarInfo(name)
                if kind == "file":
                    member.size = len(contents)
                    archive.addfile(member, io.BytesIO(contents))
                elif kind == "directory":
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
                elif kind in {"symlink", "hardlink"}:
                    member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                    member.linkname = contents
                    archive.addfile(member)
                else:
                    member.type = tarfile.CHRTYPE
                    archive.addfile(member)
        buffer.seek(0)
        return buffer

    def validate_archive(self, members):
        with tarfile.open(fileobj=self.tar_buffer(members), mode="r:xz") as archive:
            return runtime.archive_members(archive, "release")

    def launch_output(self, bits, sha="a" * 64, **changes):
        report = {"executed": True, "process_finished": True, "return_code": 0,
                  "pe": {"architecture": "x86_64" if bits == 64 else "x86", "sha256": sha},
                  "runtime": {"wine_version": [11, 0, 0], "wine_version_report_verified": True},
                  "shell": False}
        report.update(changes)
        return runtime.payload_token(bits) + json.dumps(report).encode("utf-8")

    def marker(self, bits):
        marker = self.root / f"win{bits}.result"
        marker.write_bytes(runtime.payload_token(bits))
        return marker

    def test_pinned_manifest_is_complete_and_primary(self):
        self.assertEqual(self.pins["wine"]["version"], "11.0")
        self.assertEqual(self.pins["wine"]["source_commit"], "db11d0fe6a169c457e23d007e20404643d067aa8")
        self.assertEqual(self.pins["llvm_mingw"]["version"], "20260908")
        self.assertEqual(self.pins["bison"]["version"], "3.8.2")
        self.assertEqual(self.pins["wine"]["license"], "LGPL-2.1-or-later")
        self.assertEqual(set(self.pins), {"schema", "wine", "bison", "llvm_mingw"})

    def test_manifest_rejects_mutable_unhashed_sources(self):
        for value in ("", "latest", "a" * 63, ["a"]):
            with self.subTest(value=value):
                path = self.mutated_pins(lambda pins: pins["wine"].update(sha256=value))
                self.error("pins_sha256", runtime.load_pins, path)

    def test_manifest_rejects_nonprimary_or_nonhttps_sources(self):
        for value in ("http://dl.winehq.org/wine.tar.xz", "https://example.org/wine.tar.xz",
                      "https://name:secret@dl.winehq.org/wine.tar.xz",
                      "https://dl.winehq.org/wine.tar.xz?latest=1", 123):
            with self.subTest(value=value):
                path = self.mutated_pins(lambda pins: pins["wine"].update(url=value))
                self.error("pins_source_url", runtime.load_pins, path)

    def test_manifest_limits_size_and_archive_root(self):
        for size in (-1, 0, True, runtime.MAX_DOWNLOAD + 1):
            path = self.mutated_pins(lambda pins: pins["wine"].update(bytes=size))
            self.error("pins_size", runtime.load_pins, path)
        for root in ("../outside", "/absolute", "name/other", 123):
            path = self.mutated_pins(lambda pins: pins["wine"].update(archive_root=root))
            self.error("pins_archive_root", runtime.load_pins, path)

    def test_plan_is_read_only_and_contains_no_runtime_claim(self):
        with mock.patch.object(runtime, "urlopen") as download, mock.patch.object(runtime.subprocess, "Popen") as process:
            report = runtime.build_plan(self.pins)
        download.assert_not_called()
        process.assert_not_called()
        self.assertFalse(report["executed"])
        self.assertFalse(report["wine_runtime_tested"])
        self.assertFalse(report["gpu_acceleration_tested"])
        self.assertEqual(report["pe_architectures"], ["x86_64", "x86"])

    def test_windows_build_guard_precedes_files_downloads_and_processes(self):
        target = self.root / "must-not-be-created"
        with mock.patch.object(runtime.platform, "system", return_value="Windows"), \
                mock.patch.object(runtime, "urlopen") as download, \
                mock.patch.object(runtime.subprocess, "Popen") as process:
            self.error("requires_native_intel_macos", runtime.build_and_test, target, self.pins, 4)
        self.assertFalse(target.exists())
        download.assert_not_called()
        process.assert_not_called()

    def test_arm_macos_build_is_rejected(self):
        with mock.patch.object(runtime.platform, "system", return_value="Darwin"), \
                mock.patch.object(runtime.platform, "machine", return_value="arm64"):
            self.error("requires_native_intel_macos", runtime.require_native_host)

    def test_build_root_rejects_nonempty_directory(self):
        (self.root / "existing-data").write_text("retain", encoding="utf-8")
        self.error("build_root_must_be_fresh", runtime.fresh_build_root, self.root)
        self.assertEqual((self.root / "existing-data").read_text(encoding="utf-8"), "retain")

    def test_download_accepts_only_exact_hash_and_bytes(self):
        data = b"own bounded archive fixture"
        item = self.download_item(data)
        destination = self.root / "verified.tar.xz"
        with mock.patch.object(runtime, "urlopen", return_value=Response(data, length=len(data))) as download:
            report = runtime.checked_download(item, destination)
        self.assertEqual(destination.read_bytes(), data)
        self.assertTrue(report["verified"])
        self.assertEqual(download.call_args.kwargs["timeout"], 60)

    def test_download_rejects_hash_corruption(self):
        expected = b"original"
        with mock.patch.object(runtime, "urlopen", return_value=Response(b"tampered")):
            self.error("source_integrity_failed", runtime.checked_download,
                       self.download_item(expected), self.root / "corrupt")

    def test_download_rejects_short_and_oversized_streams(self):
        item = self.download_item(b"1234")
        for value, code in ((b"123", "source_integrity_failed"), (b"12345", "source_size_limit")):
            with self.subTest(value=value), mock.patch.object(runtime, "urlopen", return_value=Response(value)):
                self.error(code, runtime.checked_download, item, self.root / code)

    def test_download_checks_secondary_wine_digest(self):
        item = self.download_item(b"verified") | {"sha512": "0" * 128}
        with mock.patch.object(runtime, "urlopen", return_value=Response(b"verified")):
            self.error("source_sha512_failed", runtime.checked_download, item, self.root / "secondary")

    def test_download_rejects_bad_content_length_before_body(self):
        response = Response(b"1234", length=999)
        with mock.patch.object(runtime, "urlopen", return_value=response):
            self.error("source_content_length", runtime.checked_download,
                       self.download_item(b"1234"), self.root / "length")
        self.assertEqual(response.tell() if not response.closed else 0, 0)

    def test_download_rejects_unapproved_redirect(self):
        for index, url in enumerate(("http://dl.winehq.org/a", "https://example.org/a")):
            with mock.patch.object(runtime, "urlopen", return_value=Response(b"1234", url=url)):
                self.error("source_redirect_not_allowed", runtime.checked_download,
                           self.download_item(b"1234"), self.root / f"redirect-{index}")

    def test_archive_rejects_traversal_absolute_and_wrong_root(self):
        for name in ("../escape", "/release/file", "release/../../escape", "different/file",
                     "release\\escape", "release/C:escape"):
            with self.subTest(name=name):
                self.error("archive_path_outside_root", self.validate_archive, [(name, "file", b"x")])

    def test_archive_rejects_duplicate_and_special_files(self):
        self.error("archive_duplicate_path", self.validate_archive,
                   [("release/file", "file", b"a"), ("release/file", "file", b"b")])
        self.error("archive_special_file", self.validate_archive, [("release/device", "device", b"")])

    def test_archive_preserves_internal_relative_links(self):
        members = self.validate_archive([("release/include", "directory", b""),
            ("release/bin/real", "file", b"compiler fixture"),
            ("release/bin/alias", "symlink", "real"),
            ("release/include-alias", "symlink", "include"),
            ("release/bin/copy", "hardlink", "release/bin/real")])
        self.assertEqual(len(members), 5)

    def test_archive_rejects_escaping_link_targets(self):
        for target in ("../../outside", "/outside", "C:\\outside"):
            with self.subTest(target=target):
                self.assertRaises(runtime.RuntimeBuildError, self.validate_archive,
                                  [("release/bin/link", "symlink", target)])

    def test_archive_rejects_files_under_planned_links(self):
        self.error("archive_file_under_link", self.validate_archive,
                   [("release/alias", "symlink", "real"), ("release/alias/write", "file", b"x")])

    def test_archive_enforces_count_and_expansion_budgets(self):
        with mock.patch.object(runtime, "MAX_ARCHIVE_MEMBERS", 1):
            self.error("archive_member_limit", self.validate_archive,
                       [("release/a", "file", b"a"), ("release/b", "file", b"b")])
        with mock.patch.object(runtime, "MAX_ARCHIVE_BYTES", 3):
            self.error("archive_byte_limit", self.validate_archive, [("release/a", "file", b"1234")])

    def test_extracts_regular_archive_into_fresh_destination(self):
        path = self.root / "own.tar.xz"
        path.write_bytes(self.tar_buffer([("release/file", "file", b"source fixture")]).getvalue())
        extracted = runtime.extract_source(path, self.root / "extracted", "release")
        self.assertEqual((extracted / "file").read_bytes(), b"source fixture")

    def test_compiler_arguments_keep_metacharacters_literal_and_crt_disabled(self):
        source = Path("source with space;$(value).c")
        target = Path("output with space &.exe")
        for bits in (32, 64):
            argv = runtime.compiler_arguments(Path("chosen compiler"), source, target, bits)
            self.assertIn(str(source), argv)
            self.assertIn(str(target), argv)
            self.assertIn("-nostdlib", argv)
            self.assertIn("-lkernel32", argv)
            self.assertIn(f"-DLUNARBRIDGE_BITS={bits}", argv)
            self.assertNotIn("-lmsvcrt", argv)
            self.assertIn("-Wl,--entry," + ("smoke_entry" if bits == 64 else "_smoke_entry"), argv)
        self.error("payload_architecture", runtime.compiler_arguments, Path("c"), source, target, 16)

    def test_wine_configure_requests_new_wow64_and_no_graphics_dependency(self):
        prefix = Path("own prefix;$(literal)")
        argv = runtime.wine_configure_arguments(Path("source directory"), prefix)
        self.assertEqual(argv[:2], ["/bin/sh", str(Path("source directory") / "configure")])
        self.assertIn(f"--prefix={prefix}", argv)
        self.assertIn("--enable-archs=i386,x86_64", argv)
        self.assertIn("--with-mingw=llvm-mingw", argv)
        self.assertIn("--without-opengl", argv)
        self.assertIn("--without-vulkan", argv)
        self.assertNotIn("--without-pthread", argv)

    def test_result_check_accepts_x64_and_wow64_only_with_all_evidence(self):
        for bits in (64, 32):
            record = runtime.verify_payload_result(bits, 0, self.launch_output(bits), self.marker(bits), "a" * 64)
            self.assertTrue(record["real_windows_pe_executed"])
            self.assertEqual(record["wow64_verified_on_ci"], bits == 32)
            self.assertFalse(record["gpu_tested"])

    def test_result_check_rejects_nonzero_and_missing_tokens(self):
        marker = self.marker(64)
        self.error("payload_process_failed", runtime.verify_payload_result,
                   64, 1, self.launch_output(64), marker, "a" * 64)
        self.error("payload_stdout_token", runtime.verify_payload_result,
                   64, 0, b"fake success", marker, "a" * 64)

    def test_result_check_requires_launcher_hash_architecture_and_runtime(self):
        marker = self.marker(64)
        for changes in ({"executed": False}, {"shell": True}, {"process_finished": False},
                        {"pe": {"architecture": "x86", "sha256": "a" * 64}},
                        {"pe": {"architecture": "x86_64", "sha256": "b" * 64}},
                        {"runtime": {"wine_version": [10, 0, 0], "wine_version_report_verified": True}},
                        {"runtime": []}, {"pe": []}):
            with self.subTest(changes=changes):
                self.error("payload_launch_report", runtime.verify_payload_result,
                           64, 0, self.launch_output(64, **changes), marker, "a" * 64)

    def test_result_check_rejects_missing_or_wrong_marker(self):
        marker = self.root / "absent.result"
        self.error("payload_marker_result", runtime.verify_payload_result,
                   32, 0, self.launch_output(32), marker, "a" * 64)
        marker.write_bytes(b"old result")
        self.error("payload_marker_result", runtime.verify_payload_result,
                   32, 0, self.launch_output(32), marker, "a" * 64)

    def test_public_log_redaction_removes_selected_roots(self):
        text = f"root={self.root}; source={runtime.ROOT}; owner={Path.home()}"
        redacted = runtime.sanitize_text(text, self.root)
        self.assertNotIn(str(self.root), redacted)
        self.assertNotIn(str(runtime.ROOT), redacted)
        self.assertNotIn(str(Path.home()), redacted)
        self.assertIn("<build-root>", redacted)

    def test_runtime_package_has_stable_metadata_and_relative_paths(self):
        source = self.root / "install"
        source.mkdir()
        (source / "own fixture").write_bytes(b"metadata fixture, not an executable")
        first, second = self.root / "one.tar.xz", self.root / "two.tar.xz"
        record = runtime.pack_runtime(source, first)
        runtime.pack_runtime(source, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertFalse(record["relocation_verified"])
        with tarfile.open(first, "r:xz") as archive:
            for member in archive:
                self.assertTrue(member.name.startswith("wine-11.0-intel-diagnostic"))
                self.assertEqual(member.mtime, runtime.SOURCE_DATE_EPOCH)
                self.assertEqual(member.uname, "")


if __name__ == "__main__":
    unittest.main()
