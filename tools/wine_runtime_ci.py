# SPDX-License-Identifier: GPL-3.0-only
"""Build pinned upstream Wine and execute own PE payloads on Intel-macOS CI.

--plan is portable and read-only. --build-and-test is explicitly Mac-only and
writes exclusively to a fresh selected build root. It installs no system tools.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pe_inspector import InspectionError, inspect_pe
from windows_compatibility import PREFIX_ID, PREFIX_MARKER, inspect_wine

ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 75000
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_LOG = 32 * 1024 * 1024
SOURCE_DATE_EPOCH = 1768435200
SOURCE_FILES = (
    "ci/runtime-pins.json", "ci/payload/runtime_smoke.c", "tools/wine_runtime_ci.py",
    "tools/pe_inspector.py", "tools/windows_compatibility.py",
    ".github/workflows/wine-runtime.yml",
)
WITHOUT_FEATURES = (
    "alsa", "capi", "coreaudio", "cups", "dbus", "ffmpeg", "fontconfig",
    "freetype", "gettext", "gettextpo", "gphoto", "gnutls", "gssapi", "gstreamer",
    "hwloc", "inotify", "krb5", "netapi", "opencl", "opengl", "oss", "pcap",
    "pcsclite", "pulse", "sane", "sdl", "udev", "usb", "v4l2", "vulkan", "wayland",
)
UPSTREAM_HOSTS = {
    "wine": "dl.winehq.org", "bison": "ftp.gnu.org", "llvm_mingw": "github.com",
}
DOWNLOAD_HOSTS = frozenset(UPSTREAM_HOSTS.values()) | {
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
}


class RuntimeBuildError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pins(path: Path = ROOT / "ci/runtime-pins.json") -> dict:
    try:
        if path.stat().st_size > 16384:
            raise RuntimeBuildError("pins_limit")
        pins = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeBuildError("pins_invalid") from exc
    if not isinstance(pins, dict) or set(pins) != {"schema", *UPSTREAM_HOSTS} or pins["schema"] != 1:
        raise RuntimeBuildError("pins_schema")
    for name, host in UPSTREAM_HOSTS.items():
        item = pins[name]
        if not isinstance(item, dict):
            raise RuntimeBuildError("pins_entry")
        if not isinstance(item.get("url"), str):
            raise RuntimeBuildError("pins_source_url")
        parsed = urlparse(item["url"])
        if (parsed.scheme != "https" or parsed.hostname != host or parsed.username
                or parsed.password or parsed.port or parsed.query or parsed.fragment
                or not parsed.path.endswith(".tar.xz")):
            raise RuntimeBuildError("pins_source_url")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise RuntimeBuildError("pins_sha256")
        if type(item.get("bytes")) is not int or not 0 < item["bytes"] <= MAX_DOWNLOAD:
            raise RuntimeBuildError("pins_size")
        if (not isinstance(item.get("archive_root"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item["archive_root"])):
            raise RuntimeBuildError("pins_archive_root")
        if not isinstance(item.get("version"), str) or not isinstance(item.get("license"), str):
            raise RuntimeBuildError("pins_metadata")
    if (not isinstance(pins["wine"].get("sha512"), str)
            or not re.fullmatch(r"[0-9a-f]{128}", pins["wine"]["sha512"])):
        raise RuntimeBuildError("pins_wine_sha512")
    for name in ("wine", "llvm_mingw"):
        if (not isinstance(pins[name].get("source_commit"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", pins[name]["source_commit"])):
            raise RuntimeBuildError("pins_source_commit")
    return pins


def build_plan(pins: dict) -> dict:
    return {
        "schema": 1, "operation": "source_build_and_own_payload_test", "sources": pins,
        "host_required": "native Intel macOS 26 CI; Python >= 3.12",
        "native_tools": ["Apple clang/SDK", "make", "flex >= 2.5.33", "m4"],
        "built_build_dependency": "GNU Bison 3.8.2",
        "pe_architectures": ["x86_64", "x86"], "wine_archs": ["i386", "x86_64"],
        "optional_features_disabled": list(WITHOUT_FEATURES) + ["x"],
        "purpose": "console loader/Kernel32/WoW64 proof; diagnostic runtime",
        "system_installation": False, "policy_changes": False, "executed": False,
        "wine_runtime_tested": False, "native_target_tested": False,
        "gpu_acceleration_tested": False, "windows_user_application_tested": False,
        "build_time_minutes_estimate": [20, 60], "estimate_measured": False,
        "job_timeout_minutes": 90,
    }


def require_native_host() -> None:
    if (platform.system() != "Darwin"
            or platform.machine().lower() not in {"x86_64", "amd64"}):
        raise RuntimeBuildError("requires_native_intel_macos")
    if sys.version_info < (3, 12) or not hasattr(tarfile, "data_filter"):
        raise RuntimeBuildError("runtime_build_requires_python_3_12")


def fresh_build_root(path: Path) -> Path:
    selected = path.expanduser().resolve()
    if selected in {Path(selected.anchor), Path.home().resolve(), ROOT}:
        raise RuntimeBuildError("build_root_must_be_dedicated")
    if selected.exists() and (not selected.is_dir() or any(selected.iterdir())):
        raise RuntimeBuildError("build_root_must_be_fresh")
    selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    return selected


def checked_download(item: dict, destination: Path) -> dict:
    """Only allowlisted HTTPS sources, bounded streamed bytes, exact hashes."""
    digest, secondary = hashlib.sha256(), hashlib.sha512()
    count = 0
    request = Request(item["url"], headers={"User-Agent": "LunarBridge-runtime-source-build/1"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("xb") as target:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname not in DOWNLOAD_HOSTS:
                raise RuntimeBuildError("source_redirect_not_allowed")
            header_size = response.headers.get("Content-Length")
            if header_size and (not header_size.isdigit() or int(header_size) != item["bytes"]):
                raise RuntimeBuildError("source_content_length")
            while True:
                block = response.read(65536)
                if not block:
                    break
                count += len(block)
                if count > item["bytes"]:
                    raise RuntimeBuildError("source_size_limit")
                target.write(block)
                digest.update(block)
                secondary.update(block)
    except (OSError, ValueError) as exc:
        raise RuntimeBuildError("source_download_failed") from exc
    if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise RuntimeBuildError("source_integrity_failed")
    if "sha512" in item and secondary.hexdigest() != item["sha512"]:
        raise RuntimeBuildError("source_sha512_failed")
    return {"bytes": count, "sha256": digest.hexdigest(), "verified": True}


def normalized_link(member: tarfile.TarInfo, root_name: str) -> PurePosixPath:
    if not member.linkname or "\\" in member.linkname or ":" in member.linkname:
        raise RuntimeBuildError("archive_link_invalid")
    raw = PurePosixPath(member.linkname)
    if raw.is_absolute():
        raise RuntimeBuildError("archive_link_outside_root")
    parts = []
    base = PurePosixPath(member.name).parent / raw if member.issym() else raw
    for part in base.parts:
        if part == "..":
            if not parts:
                raise RuntimeBuildError("archive_link_outside_root")
            parts.pop()
        elif part != ".":
            parts.append(part)
    if not parts or parts[0] != root_name:
        raise RuntimeBuildError("archive_link_outside_root")
    return PurePosixPath(*parts)


def archive_members(archive: tarfile.TarFile, root_name: str) -> list[tarfile.TarInfo]:
    """Bound tar metadata, names, link destinations and extracted byte budget."""
    members, names, links, total = [], set(), set(), 0
    for member in archive:
        if len(members) >= MAX_ARCHIVE_MEMBERS:
            raise RuntimeBuildError("archive_member_limit")
        path = PurePosixPath(member.name)
        if (path.is_absolute() or not path.parts or path.parts[0] != root_name
                or ".." in path.parts or "\\" in member.name or ":" in member.name
                or len(member.name) > 1024):
            raise RuntimeBuildError("archive_path_outside_root")
        key = str(path)
        if key in names:
            raise RuntimeBuildError("archive_duplicate_path")
        names.add(key)
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise RuntimeBuildError("archive_special_file")
        if member.issym() or member.islnk():
            normalized_link(member, root_name)
            links.add(path)
        if member.isfile():
            total += member.size
            if member.size < 0 or total > MAX_ARCHIVE_BYTES:
                raise RuntimeBuildError("archive_byte_limit")
        members.append(member)
    for member in members:
        if any(parent in links for parent in PurePosixPath(member.name).parents):
            raise RuntimeBuildError("archive_file_under_link")
    if not members:
        raise RuntimeBuildError("archive_empty")
    return members


def extract_source(archive_path: Path, destination: Path, root_name: str) -> Path:
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeBuildError("archive_destination_not_fresh")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:xz") as archive:
            members = archive_members(archive, root_name)
            archive.extractall(destination, members=members, filter="data")
    except (tarfile.TarError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeBuildError("archive_extraction_failed") from exc
    extracted = destination / root_name
    if not extracted.is_dir():
        raise RuntimeBuildError("archive_root_missing")
    return extracted


def compiler_arguments(compiler: Path, source: Path, target: Path, bits: int) -> list[str]:
    if bits not in {32, 64}:
        raise RuntimeBuildError("payload_architecture")
    entry = "smoke_entry" if bits == 64 else "_smoke_entry"
    return [str(compiler), "-std=c11", "-Os", "-Wall", "-Wextra", "-Werror",
            "-nostdlib", "-fno-stack-protector", "-fno-ident", "-D_WIN32_WINNT=0x0601",
            f"-DLUNARBRIDGE_BITS={bits}", "-Wl,--no-insert-timestamp",
            "-Wl,--subsystem,console", f"-Wl,--entry,{entry}", str(source), "-o", str(target),
            "-lkernel32"]


def wine_configure_arguments(source: Path, prefix: Path) -> list[str]:
    return ["/bin/sh", str(source / "configure"), f"--prefix={prefix}",
            "--enable-archs=i386,x86_64", "--with-mingw=llvm-mingw", "--disable-tests",
            "--disable-win16", "--without-x", *[f"--without-{name}" for name in WITHOUT_FEATURES]]


def payload_token(bits: int) -> bytes:
    if bits not in {32, 64}:
        raise RuntimeBuildError("payload_architecture")
    return f"LUNARBRIDGE_WIN{bits}_RUNTIME_OK\n".encode("ascii")


def verify_payload_result(bits: int, code: int, stdout: bytes, marker: Path,
                          expected_sha256: str) -> dict:
    token = payload_token(bits)
    if code != 0:
        raise RuntimeBuildError("payload_process_failed")
    if len(stdout) > 1024 * 1024 or not stdout.startswith(token):
        raise RuntimeBuildError("payload_stdout_token")
    try:
        report = json.loads(stdout[len(token):].decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeBuildError("payload_launch_report") from exc
    expected_arch = "x86_64" if bits == 64 else "x86"
    if (not isinstance(report, dict) or not isinstance(report.get("pe"), dict)
            or not isinstance(report.get("runtime"), dict) or report.get("executed") is not True
            or report.get("process_finished") is not True or report.get("return_code") != 0
            or report.get("pe", {}).get("architecture") != expected_arch
            or report.get("pe", {}).get("sha256") != expected_sha256
            or report.get("runtime", {}).get("wine_version") != [11, 0, 0]
            or report.get("runtime", {}).get("wine_version_report_verified") is not True
            or report.get("shell") is not False):
        raise RuntimeBuildError("payload_launch_report")
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_size != len(token)
            or marker.read_bytes() != token):
        raise RuntimeBuildError("payload_marker_result")
    return {"architecture": expected_arch, "sha256": expected_sha256, "return_code": 0,
            "stdout_token_verified": True, "file_token_verified": True,
            "real_windows_pe_executed": True, "launcher_used": True,
            "wow64_verified_on_ci": bits == 32, "gpu_tested": False}


def sanitize_text(value: str, build_root: Path) -> str:
    replacements = [(str(build_root), "<build-root>"), (str(ROOT), "<repository>"),
                    (str(Path.home()), "<home>")]
    temporary = os.environ.get("TMPDIR", "")
    if len(temporary) >= 5:
        replacements.append((temporary.rstrip("/"), "<temporary>"))
    for source, target in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if len(source) >= 5:
            value = value.replace(source, target)
    return value


class BuildRunner:
    def __init__(self, root: Path, report: dict):
        self.root, self.report = root, report
        self.logs = root / "private-logs"
        self.logs.mkdir()
        self.environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C",
                            "LC_ALL": "C", "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH)}
        for key in ("HOME", "TMPDIR", "USER", "LOGNAME"):
            if key in os.environ:
                self.environment[key] = os.environ[key]
        self.environment.update({"CC": "/usr/bin/clang", "CXX": "/usr/bin/clang++", "LD": "/usr/bin/ld",
                                 "CFLAGS": "-O2 -g0", "CXXFLAGS": "-O2 -g0",
                                 "i386_CFLAGS": "-O2 -g0", "x86_64_CFLAGS": "-O2 -g0",
                                 "M4": "/usr/bin/m4"})

    def run(self, name: str, argv: list[str], cwd: Path, timeout: int,
            environment: dict | None = None, allow_failure: bool = False,
            separate_stderr: bool = False) -> tuple[int, bytes]:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise RuntimeBuildError("stage_name_invalid")
        print(f"Stage {name}: start", flush=True)
        entry = {"name": name, "argv": [sanitize_text(arg, self.root) for arg in argv],
                 "shell": False, "timeout_seconds": timeout}
        self.report["stages"].append(entry)
        started = time.monotonic()
        log_path = self.logs / f"{name}.log"
        error_path = self.logs / f"{name}.stderr.log"
        try:
            with log_path.open("xb") as output, error_path.open("xb") as errors:
                process = subprocess.Popen(argv, cwd=str(cwd), env=environment or self.environment,
                                           stdin=subprocess.DEVNULL, stdout=output,
                                           stderr=errors if separate_stderr else subprocess.STDOUT,
                                           shell=False, start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    entry["timeout"] = True
                    raise RuntimeBuildError("build_stage_timeout")
            entry.update({"return_code": code, "duration_seconds": round(time.monotonic() - started, 3)})
            if log_path.stat().st_size > MAX_LOG or error_path.stat().st_size > MAX_LOG:
                raise RuntimeBuildError("build_log_limit")
            stdout = log_path.read_bytes()
            print(f"Stage {name}: exit {code}, {entry['duration_seconds']} s", flush=True)
            if code != 0 and not allow_failure:
                raise RuntimeBuildError(f"stage_failed_{name}")
            return code, stdout
        except OSError as exc:
            raise RuntimeBuildError("build_process_failed") from exc

    def publish_logs(self, output: Path) -> None:
        logs = output / "logs"
        logs.mkdir(exist_ok=True)
        for source in self.logs.iterdir():
            with source.open("rb") as data:
                raw = data.read(MAX_LOG)
            text = sanitize_text(raw.decode("utf-8", errors="replace"), self.root)
            if source.stat().st_size > MAX_LOG:
                text += "\n<log-truncated-at-limit>\n"
            (logs / source.name).write_text(text, encoding="utf-8", newline="\n")


def retain_licenses(source: Path, target: Path, required: bool = True) -> int:
    count = 0
    for path in source.rglob("*"):
        if (path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024
                and path.name.upper().startswith(("COPYING", "LICENSE", "NOTICE"))):
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            count += 1
    if required and count == 0:
        raise RuntimeBuildError("upstream_license_not_found")
    return count


def pack_runtime(source: Path, target: Path) -> dict:
    def fixed_metadata(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid, info.gid, info.uname, info.gname = 0, 0, "", ""
        info.mtime = SOURCE_DATE_EPOCH
        info.mode &= 0o777
        return info
    with tarfile.open(target, "w:xz", preset=6, dereference=False) as package:
        package.add(source, arcname="wine-11.0-intel-diagnostic", filter=fixed_metadata)
    return {"file": target.name, "sha256": sha256_file(target), "bytes": target.stat().st_size,
            "configured_for_ci_prefix": True, "relocation_verified": False,
            "complete_application_runtime": False}


def build_and_test(build_root: Path, pins: dict, jobs: int) -> dict:
    # This check precedes directories, downloads and every external process.
    require_native_host()
    if not 1 <= jobs <= 4:
        raise RuntimeBuildError("jobs_limit")
    root = fresh_build_root(build_root)
    output = root / "out"
    sources = output / "sources"
    sources.mkdir(parents=True)
    downloads = root / "downloads"
    downloads.mkdir()
    report = build_plan(pins)
    report.update({"started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "host_system": platform.system(), "host_machine": platform.machine(),
                   "python_version": platform.python_version(), "stages": [], "payloads": [],
                   "source_sha256": {name: sha256_file(ROOT / name) for name in SOURCE_FILES},
                   "result": "in_progress", "jobs": jobs, "downloads": {},
                   "repository_url": "https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility"})
    revision = os.environ.get("GITHUB_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", revision):
        report["repository_source_commit"] = revision
    for name in (*SOURCE_FILES, "LICENSE", "NOTICE"):
        retained_source = output / "recipe" / name
        retained_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, retained_source)
    runner = BuildRunner(root, report)
    prefix = root / "prefixes" / "smoke-wow64"
    wine_prefix = root / "install" / "wine"
    server = wine_prefix / "bin" / "wineserver"
    smoke_environment = None
    start = time.monotonic()
    try:
        versions = {}
        for name, argv in (
            ("host-macos", ["/usr/bin/sw_vers", "-productVersion"]),
            ("host-clang", ["/usr/bin/clang", "--version"]),
            ("host-sdk", ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"]),
            ("host-make", ["/usr/bin/make", "--version"]),
            ("host-flex", ["/usr/bin/flex", "--version"]),
            ("host-m4", ["/usr/bin/m4", "--version"]),
        ):
            _, stdout = runner.run(name, argv, root, 30)
            versions[name] = sanitize_text(stdout.decode("utf-8", errors="replace")[:4096].strip(), root)
        if not versions["host-macos"].startswith("26."):
            raise RuntimeBuildError("runtime_ci_requires_macos_26")
        flex = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", versions["host-flex"])
        if not flex or tuple(map(int, flex.groups())) < (2, 5, 33):
            raise RuntimeBuildError("system_flex_too_old")
        report["host_tools"] = versions
        extracted = {}
        for name in ("bison", "llvm_mingw", "wine"):
            item = pins[name]
            print(f"Source {name}: download and integrity check", flush=True)
            # Retain complete Wine/Bison source; the compiler binary is not redistributed.
            archive_directory = downloads if name == "llvm_mingw" else sources
            archive = archive_directory / Path(urlparse(item["url"]).path).name
            report["downloads"][name] = checked_download(item, archive)
            extracted[name] = extract_source(archive, root / "sources" / name, item["archive_root"])
            report.setdefault("retained_license_files", {})[name] = retain_licenses(
                extracted[name], output / "licenses" / name)
        for name in ("wine", "bison"):
            if not (extracted[name] / "configure").is_file():
                raise RuntimeBuildError("release_configure_missing")
        if (extracted["wine"] / "VERSION").read_text(encoding="ascii").strip() != "Wine version 11.0":
            raise RuntimeBuildError("wine_source_version")
        for bits, arch in ((64, "x86_64"), (32, "i686")):
            compiler = extracted["llvm_mingw"] / "bin" / f"{arch}-w64-mingw32-clang"
            runner.run(f"compiler-{bits}-version", [str(compiler), "--version"], root, 30)

        bison_build, bison_install = root / "build" / "bison", root / "install" / "bison"
        bison_build.mkdir(parents=True)
        runner.run("bison-configure", ["/bin/sh", str(extracted["bison"] / "configure"),
                   f"--prefix={bison_install}", "--disable-nls", "--disable-dependency-tracking"],
                   bison_build, 180)
        runner.run("bison-build", ["/usr/bin/make", f"-j{jobs}"], bison_build, 600)
        runner.run("bison-install", ["/usr/bin/make", "install"], bison_build, 180)
        runner.environment["PATH"] = os.pathsep.join((str(bison_install / "bin"),
            str(extracted["llvm_mingw"] / "bin"), "/usr/bin", "/bin", "/usr/sbin", "/sbin"))
        pkg_config = root / "empty-pkgconfig"
        pkg_config.mkdir()
        runner.environment["PKG_CONFIG_LIBDIR"] = str(pkg_config)
        runner.run("bison-version", [str(bison_install / "bin" / "bison"), "--version"], root, 30)
        wine_build = root / "build" / "wine"
        wine_build.mkdir()
        runner.run("wine-configure", wine_configure_arguments(extracted["wine"], wine_prefix), wine_build, 300)
        runner.run("wine-build", ["/usr/bin/make", f"-j{jobs}"], wine_build, 3600)
        runner.run("wine-install", ["/usr/bin/make", "install"], wine_build, 300)
        runtime_licenses = wine_prefix / "share" / "doc" / "wine" / "licenses"
        runtime_licenses.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(output / "licenses" / "wine", runtime_licenses / "wine")
        shutil.copytree(output / "licenses" / "llvm_mingw", runtime_licenses / "llvm-mingw")
        runtime = wine_prefix / "bin" / "wine"
        runtime_header = inspect_wine(runtime.resolve())
        if not runtime_header["intel_executable_slice"]:
            raise RuntimeBuildError("built_runtime_is_not_intel_macho")
        report["built_runtime"] = runtime_header
        runner.run("wine-version", [str(runtime), "--version"], root, 30)

        payload_source = ROOT / "ci" / "payload" / "runtime_smoke.c"
        payload_records = []
        for bits, arch in ((64, "x86_64"), (32, "i686")):
            directory = root / "payloads" / f"win{bits}"
            directory.mkdir(parents=True)
            image = directory / f"lunarbridge-win{bits}.exe"
            compiler = extracted["llvm_mingw"] / "bin" / f"{arch}-w64-mingw32-clang"
            runner.run(f"payload-{bits}-compile", compiler_arguments(compiler, payload_source, image, bits),
                       directory, 120)
            metadata = inspect_pe(image)
            if (metadata["architecture"] != ("x86_64" if bits == 64 else "x86")
                    or metadata["imports"] != ["kernel32.dll"] or metadata["delay_imports"]
                    or metadata["managed_clr"] or metadata["subsystem"] != 3 or metadata["launch_blockers"]):
                raise RuntimeBuildError("own_payload_pe_mismatch")
            payload_records.append((bits, directory, image, metadata))

        # A fresh, module-owned prefix; no GUI/Mono/Gecko dependency for these own payloads.
        prefix.mkdir(mode=0o700, parents=True)
        (prefix / PREFIX_MARKER).write_text(json.dumps(PREFIX_ID) + "\n", encoding="utf-8")
        smoke_environment = runner.environment | {"WINEPREFIX": str(prefix), "WINEDEBUG": "-all",
            "WINEARCH": "wow64", "WINEDLLOVERRIDES": "mscoree,mshtml="}
        runner.run("prefix-init", [str(runtime), "wineboot", "--init"], root, 180, smoke_environment)
        runner.run("prefix-wait", [str(server), "--wait"], root, 180, smoke_environment)
        registry = prefix / "system.reg"
        with registry.open("r", encoding="utf-8", errors="replace") as source:
            if "#arch=win64" not in source.read(4096):
                raise RuntimeBuildError("prefix_not_win64")
        report["prefix_architecture"] = "win64"
        for bits, directory, image, metadata in payload_records:
            marker = directory / f"lunarbridge-win{bits}.result"
            if marker.exists():
                raise RuntimeBuildError("payload_marker_already_exists")
            argv = [sys.executable, str(ROOT / "tools" / "windows_compatibility.py"), "launch",
                    "--wine", str(runtime), "--prefix", str(prefix), str(image)]
            code, stdout = runner.run(f"payload-{bits}-run", argv, directory, 180,
                                     smoke_environment, allow_failure=True, separate_stderr=True)
            report["payloads"].append(verify_payload_result(bits, code, stdout, marker, metadata["sha256"]))
        runtime_folder = output / "runtime"
        runtime_folder.mkdir()
        report["runtime_package"] = pack_runtime(wine_prefix, runtime_folder / "wine-11.0-intel-diagnostic.tar.xz")
        shutil.copyfile(payload_source, sources / "runtime_smoke.c")
        shutil.copyfile(ROOT / "LICENSE", output / "licenses" / "LunarBridge-GPL-3.0-only.txt")
        for bits, directory, image, metadata in payload_records:
            retained = output / "own-payloads"
            retained.mkdir(exist_ok=True)
            shutil.copyfile(image, retained / image.name)
            shutil.copyfile(directory / f"lunarbridge-win{bits}.result", retained / f"lunarbridge-win{bits}.result")
        report.update({"result": "success", "executed": True, "wine_runtime_tested": True,
                       "wow64_verified_on_ci": True, "own_windows_pe_programs_tested": 2})
    except (RuntimeBuildError, InspectionError) as exc:
        report.update({"result": "failure", "error": exc.code})
    except (OSError, ValueError, UnicodeError) as exc:
        report.update({"result": "failure", "error": "runtime_filesystem_or_metadata_error"})
    finally:
        if smoke_environment is not None and server.is_file():
            try:
                cleanup_code, _ = runner.run("prefix-stop", [str(server), "--kill"], root, 30,
                                            smoke_environment, allow_failure=True)
            except RuntimeBuildError:
                report["prefix_cleanup_completed"] = False
            else:
                report["prefix_cleanup_completed"] = cleanup_code == 0
        for name in ("bison", "wine"):
            config_log = root / "build" / name / "config.log"
            if config_log.is_file():
                with config_log.open("rb") as source:
                    text = sanitize_text(source.read(MAX_LOG).decode("utf-8", errors="replace"), root)
                (runner.logs / f"{name}-config-detail.log").write_text(text, encoding="utf-8", newline="\n")
        runner.publish_logs(output)
        report.update({"finished_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "duration_seconds": round(time.monotonic() - start, 3)})
        (output / "BUILD_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                  encoding="utf-8", newline="\n")
        (output / "REDISTRIBUTION.txt").write_text(
            "Wine diagnostic build: LGPL-2.1-or-later. Its complete unmodified upstream source archive\n"
            "and licenses accompany the runtime. Own smoke payload/source and Python builder: GPL-3.0-only.\n"
            "GNU Bison source and upstream exceptions are retained. LLVM/MinGW component licenses are\n"
            "retained separately; toolchain binary is a build dependency, not packaged for use.\n"
            "See BUILD_REPORT.json for exact URLs, hashes, recipe revisions, tools and build flags.\n"
            "The runtime was configured for this CI prefix; relocation and user-app support are untested.\n",
            encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Pinned Wine 11 diagnostic build and own PE runtime test.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true", help="Read-only portable preparation report")
    action.add_argument("--build-and-test", action="store_true", help="Explicit Intel-macOS26-only CI build")
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    options = parser.parse_args()
    try:
        pins = load_pins()
        if options.plan:
            print(json.dumps(build_plan(pins), indent=2, sort_keys=True))
            return 0
        if options.build_root is None:
            raise RuntimeBuildError("explicit_fresh_build_root_required")
        report = build_and_test(options.build_root, pins, options.jobs)
        print(json.dumps({"result": report["result"], "duration_seconds": report["duration_seconds"],
                          "error": report.get("error"), "payloads": report["payloads"],
                          "wine_runtime_tested": report["wine_runtime_tested"],
                          "native_target_tested": False, "gpu_acceleration_tested": False}, sort_keys=True))
        return 0 if report["result"] == "success" else 1
    except RuntimeBuildError as exc:
        print(json.dumps({"result": "failure", "error": exc.code, "wine_runtime_tested": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
