# SPDX-License-Identifier: GPL-3.0-only
"""Read bounded PE metadata without loading or executing the selected image."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import struct
from typing import BinaryIO

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_IMPORTS = 512
MAX_DLL_BYTES = 256
MACHINES = {0x14C: "x86", 0x8664: "x86_64", 0xAA64: "arm64",
            0xA641: "arm64ec", 0xA64E: "arm64x", 0x1C4: "arm32"}


class InspectionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class BoundedFile:
    """Every allocation is bounded; hashing streams in 64 KiB chunks."""

    def __init__(self, path: Path):
        self.file = None
        try:
            self.file: BinaryIO = path.open("rb")
            info = os.fstat(self.file.fileno())
        except (OSError, ValueError) as exc:
            if self.file is not None:
                self.file.close()
            raise InspectionError("selected_file_unreadable") from exc
        self.size = info.st_size
        if not stat.S_ISREG(info.st_mode) or not 1 <= self.size <= MAX_FILE_BYTES:
            self.file.close()
            raise InspectionError("file_type_or_size_limit")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.file.close()

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or length > 65536 or offset + length > self.size:
            raise InspectionError("file_range")
        self.file.seek(offset)
        data = self.file.read(length)
        if len(data) != length:
            raise InspectionError("file_changed_or_truncated")
        return data

    def sha256(self) -> str:
        digest = hashlib.sha256()
        self.file.seek(0)
        remaining = self.size
        while remaining:
            data = self.file.read(min(65536, remaining))
            if not data:
                raise InspectionError("file_changed_or_truncated")
            digest.update(data)
            remaining -= len(data)
        if self.file.read(1) or os.fstat(self.file.fileno()).st_size != self.size:
            raise InspectionError("file_changed_or_truncated")
        return digest.hexdigest()


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _overlap(ranges: list[tuple[int, int]]) -> bool:
    ordered = sorted(ranges)
    return any(first[1] > second[0] for first, second in zip(ordered, ordered[1:]))


def _runtime_hints(imports: list[str], managed: bool) -> list[str]:
    hints = set()
    if managed or "mscoree.dll" in imports:
        hints.add("managed_runtime_family_unverified")
    versions = {"80": "2005", "90": "2008", "100": "2010",
                "110": "2012", "120": "2013", "140": "2015_or_later"}
    for dll in imports:
        for suffix, version in versions.items():
            if re.fullmatch(r"(?:msvcr|msvcp|vcruntime|mfc)" + suffix + r"(?:_\d+)?\.dll", dll):
                hints.add("visual_cpp_" + version + "_candidate")
        if dll == "ucrtbase.dll" or dll.startswith("api-ms-win-crt-"):
            hints.add("universal_c_runtime_candidate")
        if dll in {"hostfxr.dll", "hostpolicy.dll", "coreclr.dll"}:
            hints.add("dotnet_runtime_candidate")
    return sorted(hints)


def inspect_pe(path: Path | str) -> dict:
    """Inspect a selected PE file. Findings are hints, never a compatibility verdict."""
    with BoundedFile(Path(path)) as source:
        dos = source.read(0, 64)
        if dos[:2] != b"MZ":
            raise InspectionError("dos_signature")
        pe_offset = _u32(dos, 60)
        if pe_offset < 64:
            raise InspectionError("pe_header_offset")
        header = source.read(pe_offset, 24)
        if header[:4] != b"PE\0\0":
            raise InspectionError("pe_signature")
        machine, section_count = _u16(header, 4), _u16(header, 6)
        optional_size, characteristics = _u16(header, 20), _u16(header, 22)
        if not 1 <= section_count <= 96 or not 96 <= optional_size <= 4096:
            raise InspectionError("header_limits")
        optional = source.read(pe_offset + 24, optional_size)
        magic = _u16(optional, 0)
        if magic == 0x10B:
            directory_offset, directory_count_offset = 96, 92
            image_base = _u32(optional, 28)
            pe_kind = "PE32"
        elif magic == 0x20B and optional_size >= 112:
            directory_offset, directory_count_offset = 112, 108
            image_base = struct.unpack_from("<Q", optional, 24)[0]
            pe_kind = "PE32+"
        else:
            raise InspectionError("optional_header_magic")
        if (machine == 0x14C and magic != 0x10B) or (
                machine in {0x8664, 0xAA64, 0xA641, 0xA64E} and magic != 0x20B):
            raise InspectionError("machine_header_mismatch")
        directory_count = _u32(optional, directory_count_offset)
        if directory_count > 16 or directory_offset + directory_count * 8 > optional_size:
            raise InspectionError("directory_limits")
        directories = [struct.unpack_from("<II", optional, directory_offset + i * 8)
                       for i in range(directory_count)]
        directories += [(0, 0)] * (16 - directory_count)
        size_image, size_headers = _u32(optional, 56), _u32(optional, 60)
        section_offset = pe_offset + 24 + optional_size
        section_end = section_offset + 40 * section_count
        if not section_end <= size_headers <= source.size or not size_headers <= size_image <= 0x80000000:
            raise InspectionError("image_header_range")
        sections = []
        raw_ranges, virtual_ranges = [], []
        for index in range(section_count):
            section = source.read(section_offset + index * 40, 40)
            virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", section, 8)
            span = max(virtual_size, raw_size)
            if span:
                if rva < size_headers or rva + span > size_image:
                    raise InspectionError("section_virtual_range")
                virtual_ranges.append((rva, rva + span))
            if raw_size:
                if raw_offset < size_headers or raw_offset + raw_size > source.size:
                    raise InspectionError("section_file_range")
                raw_ranges.append((raw_offset, raw_offset + raw_size))
            sections.append((rva, raw_size, raw_offset))
        if _overlap(raw_ranges) or _overlap(virtual_ranges):
            raise InspectionError("ambiguous_sections")

        def rva_offset(rva: int, count: int) -> tuple[int, int]:
            if rva < 0 or count < 1 or rva + count > size_image:
                raise InspectionError("rva_range")
            if rva + count <= size_headers:
                return rva, size_headers - rva
            for begin, raw_size, raw_offset in sections:
                if begin <= rva and rva + count <= begin + raw_size:
                    return raw_offset + rva - begin, begin + raw_size - rva
            raise InspectionError("rva_not_file_backed")

        def read_rva(rva: int, count: int) -> bytes:
            offset, _ = rva_offset(rva, count)
            return source.read(offset, count)

        def dll_name(rva: int) -> str:
            offset, available = rva_offset(rva, 1)
            data = source.read(offset, min(MAX_DLL_BYTES + 1, available))
            if b"\0" not in data:
                raise InspectionError("import_name_termination")
            raw = data.split(b"\0", 1)[0]
            if not 1 <= len(raw) <= MAX_DLL_BYTES or not re.fullmatch(rb"[A-Za-z0-9_.+\-]+", raw):
                raise InspectionError("import_name_format")
            return raw.decode("ascii").lower()

        def imports_from(index: int, descriptor_size: int, delayed: bool) -> list[str]:
            rva, size = directories[index]
            if not rva and not size:
                return []
            if not rva or size < descriptor_size or size > (MAX_IMPORTS + 1) * descriptor_size:
                raise InspectionError("import_directory_limits")
            result = []
            for offset in range(0, size - descriptor_size + 1, descriptor_size):
                descriptor = read_rva(rva + offset, descriptor_size)
                if not any(descriptor):
                    return result
                if len(result) >= MAX_IMPORTS:
                    raise InspectionError("import_count_limit")
                if delayed:
                    attributes, name_address = _u32(descriptor, 0), _u32(descriptor, 4)
                    if attributes not in {0, 1}:
                        raise InspectionError("delay_import_attributes")
                    name_rva = name_address if attributes == 1 else name_address - image_base
                else:
                    name_rva = _u32(descriptor, 12)
                result.append(dll_name(name_rva))
            raise InspectionError("import_directory_termination")

        standard_imports = sorted(set(imports_from(1, 20, False)))
        delayed_imports = sorted(set(imports_from(13, 32, True)))
        imports = sorted(set(standard_imports + delayed_imports))
        clr_rva, clr_size = directories[14]
        managed, clr_flags = bool(clr_rva or clr_size), None
        if managed:
            if not clr_rva or clr_size < 72:
                raise InspectionError("clr_directory_range")
            clr = read_rva(clr_rva, 72)
            if not 72 <= _u32(clr, 0) <= clr_size:
                raise InspectionError("clr_header_size")
            clr_flags = _u32(clr, 16)
        signature_offset, signature_size = directories[4]
        if signature_offset or signature_size:
            if not signature_offset or signature_size < 8 or signature_offset + signature_size > source.size:
                raise InspectionError("certificate_file_range")
        graphics = sorted(set(imports) & {"d3d8.dll", "d3d9.dll", "d3d10.dll", "d3d10_1.dll",
                          "d3d11.dll", "d3d12.dll", "dxgi.dll", "opengl32.dll", "vulkan-1.dll"})
        subsystem = _u16(optional, 68)
        blockers = []
        architecture = MACHINES.get(machine, "unknown")
        if architecture not in {"x86", "x86_64"}:
            blockers.append("unsupported_target_architecture")
        if not characteristics & 0x2:
            blockers.append("not_executable_image")
        if characteristics & 0x2000:
            blockers.append("dll_is_not_a_program")
        if characteristics & 0x1000 or subsystem not in {2, 3}:
            blockers.append("not_windows_userland_gui_or_console")
        return {
            "schema": 1, "format": pe_kind, "machine": machine,
            "characteristics": characteristics,
            "architecture": architecture, "bytes": source.size, "sha256": source.sha256(),
            "subsystem": subsystem, "section_count": section_count,
            "imports": standard_imports, "delay_imports": delayed_imports,
            "managed_clr": managed, "clr_flags": clr_flags,
            "requires_wow64": architecture == "x86", "runtime_hints": _runtime_hints(imports, managed),
            "graphics_imports": graphics, "signature_declared": bool(signature_offset),
            "signature_verified": False, "launch_blockers": blockers,
            "import_analysis_complete": False, "app_compatibility": "unverified",
            "executed": False,
        }
