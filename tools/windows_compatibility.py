# SPDX-License-Identifier: GPL-3.0-only
"""Explicit PE preparation and Wine invocation; no shell, downloads or policies."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tempfile
from typing import Sequence

from pe_inspector import BoundedFile, InspectionError, inspect_pe

PREFIX_MARKER = ".lunarbridge-prefix.json"
PREFIX_ID = {"schema": 1, "module": "LunarBridge-Windows-Compatibility"}
CPU_X86_64 = 0x01000007


def selected_path(value: str | Path) -> Path:
    try:
        if "\0" in str(value):
            raise ValueError("nul")
        return Path(value).expanduser().resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise InspectionError("selected_path_invalid") from exc


def inspect_wine(path: Path) -> dict:
    """Check for an Intel macOS executable, without running it or trusting its name."""
    with BoundedFile(path) as source:
        head = source.read(0, min(source.size, 4096))
        if len(head) < 32:
            raise InspectionError("wine_runtime_header")

        def thin_at(offset: int, size: int, expected_cpu: int | None = None) -> bool:
            if size < 32 or offset + size > source.size:
                raise InspectionError("wine_runtime_slice_range")
            header = source.read(offset, 32)
            if header[:4] != b"\xcf\xfa\xed\xfe":
                return False
            cpu, _, file_type = struct.unpack_from("<III", header, 4)
            if expected_cpu is not None and cpu != expected_cpu:
                raise InspectionError("wine_runtime_slice_cpu")
            return cpu == CPU_X86_64 and file_type == 2

        if head[:4] == b"\xcf\xfa\xed\xfe":
            intel = thin_at(0, source.size)
        elif head[:4] in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}:
            count = struct.unpack_from(">I", head, 4)[0]
            wide = head[:4] == b"\xca\xfe\xba\xbf"
            stride = 32 if wide else 20
            if not 1 <= count <= 8 or 8 + stride * count > len(head):
                raise InspectionError("wine_runtime_fat_limits")
            intel = False
            slices = []
            for index in range(count):
                record = source.read(8 + stride * index, stride)
                cpu = struct.unpack_from(">I", record, 0)[0]
                if wide:
                    offset, size = struct.unpack_from(">QQ", record, 8)
                else:
                    offset, size = struct.unpack_from(">II", record, 8)
                if offset < 8 + stride * count or size < 32 or offset + size > source.size:
                    raise InspectionError("wine_runtime_slice_range")
                slices.append((offset, offset + size))
                intel |= thin_at(offset, size, cpu)
            ordered = sorted(slices)
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
                raise InspectionError("wine_runtime_slice_overlap")
        else:
            raise InspectionError("wine_runtime_not_macho")
        return {"format": "Mach-O", "intel_executable_slice": intel,
                "sha256": source.sha256(), "wine_version_report_verified": False,
                "wow64_verified": False, "executed": False}


def prefix_state(path: Path) -> str:
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise InspectionError("prefix_must_be_dedicated_directory")
    if not path.exists():
        return "new"
    if not path.is_dir():
        raise InspectionError("prefix_not_directory")
    marker = path / PREFIX_MARKER
    if not marker.exists():
        if any(path.iterdir()):
            raise InspectionError("existing_prefix_not_owned_by_module")
        return "empty"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 2048:
        raise InspectionError("prefix_marker_invalid")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise InspectionError("prefix_marker_invalid") from exc
    if data != PREFIX_ID:
        raise InspectionError("prefix_marker_invalid")
    return "module_prefix"


def checked_arguments(arguments: Sequence[str]) -> tuple[str, ...]:
    values = tuple(arguments)
    if len(values) > 64 or any(not isinstance(arg, str) or "\0" in arg or len(arg) > 4096 for arg in values):
        raise InspectionError("argument_limits")
    try:
        encoded_size = sum(len(arg.encode("utf-8")) for arg in values)
    except UnicodeError as exc:
        raise InspectionError("argument_limits") from exc
    if encoded_size > 32768:
        raise InspectionError("argument_limits")
    return values


def clean_environment(prefix: Path | None = None) -> dict[str, str]:
    allowed = {"HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "LANG"}
    environment = {key: value for key, value in os.environ.items()
                   if key in allowed or key.startswith("LC_")}
    if prefix is not None:
        environment["WINEPREFIX"] = str(prefix)
    environment["WINEDEBUG"] = "-all"
    return environment


@dataclass(frozen=True)
class ExecutionPlan:
    image: Path
    wine: Path | None
    prefix: Path | None
    arguments: tuple[str, ...]
    mode: str
    pe: dict
    runtime: dict | None
    blockers: tuple[str, ...]
    prefix_status: str | None

    def report(self) -> dict:
        return {"schema": 1, "mode": self.mode, "pe": self.pe, "runtime": self.runtime,
                "launch_blockers": list(self.blockers), "prefix_state": self.prefix_status,
                "argument_count": len(self.arguments),
                "argv_template": ["<selected-wine>", "<selected-exe>", "<explicit-arguments>"],
                "shell": False, "graphics_acceleration": "unverified",
                "installation_verified": False, "executed": False}


def make_plan(image: str | Path, wine: str | Path | None = None,
              prefix: str | Path | None = None, arguments: Sequence[str] = (),
              mode: str = "run") -> ExecutionPlan:
    if mode not in {"run", "install"}:
        raise InspectionError("execution_mode_invalid")
    selected_image = selected_path(image)
    pe = inspect_pe(selected_image)
    selected_wine = selected_path(wine) if wine else None
    selected_prefix = selected_path(prefix) if prefix else None
    runtime = inspect_wine(selected_wine) if selected_wine else None
    status = prefix_state(selected_prefix) if selected_prefix else None
    blockers = list(pe["launch_blockers"])
    if selected_image.suffix.lower() != ".exe":
        blockers.append("selected_image_is_not_exe")
    if platform.system() != "Darwin" or platform.machine().lower() not in {"x86_64", "amd64"}:
        blockers.append("requires_native_intel_macos")
    if selected_wine is None:
        blockers.append("explicit_wine_executable_required")
    elif not runtime["intel_executable_slice"]:
        blockers.append("wine_runtime_missing_intel_executable")
    elif os.name != "nt" and not os.access(selected_wine, os.X_OK):
        blockers.append("wine_runtime_not_executable")
    if selected_prefix is None:
        blockers.append("explicit_dedicated_prefix_required")
    return ExecutionPlan(selected_image, selected_wine, selected_prefix,
                         checked_arguments(arguments), mode, pe, runtime, tuple(blockers), status)


def probe_runtime(path: Path) -> dict:
    if platform.system() != "Darwin" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise InspectionError("requires_native_intel_macos")
    runtime = inspect_wine(path)
    if not runtime["intel_executable_slice"] or not os.access(path, os.X_OK):
        raise InspectionError("wine_runtime_missing_intel_executable")
    try:
        # Temporary output is private, discarded, and never included in a report.
        with tempfile.TemporaryFile() as output:
            process = subprocess.run([str(path), "--version"], shell=False, check=False,
                                     stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                     env=clean_environment(), cwd=str(path.parent), timeout=5)
            if output.tell() > 65536:
                raise InspectionError("wine_version_output_limit")
            output.seek(0)
            version = output.read(65536).decode("ascii", errors="strict").strip()
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise InspectionError("wine_version_probe_failed") from exc
    match = re.fullmatch(r"wine-(\d{1,3})\.(\d{1,3})(?:\.(\d{1,3}))?(?:[ -][A-Za-z0-9_.() +\-]{1,128})?", version)
    if process.returncode != 0 or not match:
        raise InspectionError("wine_version_probe_failed")
    runtime.update({"wine_version_report_verified": True,
                    "wine_version": [int(part or 0) for part in match.groups()[:3]],
                    "wow64_verified": False, "executed": True})
    return runtime


def execute_plan(plan: ExecutionPlan) -> dict:
    """Invoked only by the explicit launch command, never by inspection or planning."""
    current = make_plan(plan.image, plan.wine, plan.prefix, plan.arguments, plan.mode)
    if current.blockers:
        raise InspectionError("launch_requirements_unmet")
    if current.pe["sha256"] != plan.pe["sha256"] or current.runtime["sha256"] != plan.runtime["sha256"]:
        raise InspectionError("selected_input_changed")
    runtime = probe_runtime(current.wine)
    # The version probe is an external process and may change either input.
    # Take fresh snapshots before writing the prefix or invoking the application.
    after_probe = make_plan(current.image, current.wine, current.prefix, current.arguments, current.mode)
    if (after_probe.pe["sha256"] != plan.pe["sha256"]
            or after_probe.runtime["sha256"] != plan.runtime["sha256"]
            or runtime["sha256"] != after_probe.runtime["sha256"]):
        raise InspectionError("selected_input_changed")
    if after_probe.blockers:
        raise InspectionError("launch_requirements_unmet")
    current = after_probe
    if current.pe["requires_wow64"] and runtime["wine_version"][0] < 11:
        raise InspectionError("x86_requires_selected_wine_11_or_newer")
    # Recheck the dedicated prefix after probing and before creating any files.
    status = prefix_state(current.prefix)
    if status in {"new", "empty"}:
        try:
            current.prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
            prefix_state(current.prefix)
            with (current.prefix / PREFIX_MARKER).open("x", encoding="utf-8") as marker:
                json.dump(PREFIX_ID, marker, sort_keys=True)
                marker.write("\n")
        except OSError as exc:
            raise InspectionError("dedicated_prefix_creation_failed") from exc
    try:
        process = subprocess.run([str(current.wine), str(current.image), *current.arguments],
                                 shell=False, check=False, env=clean_environment(current.prefix),
                                 cwd=str(current.image.parent))
    except OSError as exc:
        raise InspectionError("wine_launch_failed") from exc
    report = current.report()
    report.update({"runtime": runtime, "executed": True, "return_code": process.returncode,
                   "process_finished": True, "prefix_state": "module_prefix"})
    return report


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Einzelne EXE prüfen, Wine-Start planen oder ausdrücklich starten.")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="PE-Metadaten lesen; nichts ausführen")
    inspect.add_argument("image")
    doctor = commands.add_parser("doctor", help="Ausgewählte Wine-Datei unter Intel-macOS mit --version prüfen")
    doctor.add_argument("--wine", required=True)
    for command in ("plan", "launch"):
        action = commands.add_parser(command, help="Vorschau" if command == "plan" else "Ausdrücklicher Start")
        action.add_argument("--wine", required=command == "launch")
        action.add_argument("--prefix", required=command == "launch")
        action.add_argument("--mode", choices=("run", "install"), default="run")
        action.add_argument("image")
        action.add_argument("app_arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    try:
        if options.command == "inspect":
            report = inspect_pe(options.image)
        elif options.command == "doctor":
            report = probe_runtime(selected_path(options.wine))
        else:
            app_arguments = options.app_arguments
            if app_arguments[:1] == ["--"]:
                app_arguments = app_arguments[1:]
            plan = make_plan(options.image, options.wine, options.prefix, app_arguments, options.mode)
            report = execute_plan(plan) if options.command == "launch" else plan.report()
        print(json.dumps(report, indent=2, sort_keys=True))
        if options.command == "launch":
            return 0 if report["return_code"] == 0 else 4
        return 0
    except InspectionError as exc:
        print(json.dumps({"schema": 1, "error": exc.code, "operation_completed": False,
                          "app_executed": False}, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps({"schema": 1, "error": "filesystem_operation_failed",
                          "operation_completed": False, "app_executed": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
