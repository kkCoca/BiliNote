"""Best-effort mitigation for ctranslate2 execstack issues.

Some ctranslate2 wheels ship ELF objects that request an executable stack.
In hardened environments this can fail at load time with:

  libctranslate2-*.so: cannot enable executable stack as shared object requires

We patch the ELF PT_GNU_STACK header to clear PF_X so the loader won't try to
enable execstack.

This is a targeted workaround (ctranslate2 only) and is safe to apply multiple times.
"""

from __future__ import annotations

import glob
import os
import struct
from typing import Iterable

import site

from app.utils.logger import get_logger


logger = get_logger(__name__)


PT_GNU_STACK = 0x6474E551
PF_X = 0x1


def _candidate_shared_objects() -> Iterable[str]:
    bases: list[str] = []
    try:
        bases.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        u = site.getusersitepackages()
        if u:
            bases.append(u)
    except Exception:
        pass

    patterns = [
        "**/libctranslate2*.so*",
        "**/ctranslate2*.so*",
    ]
    seen: set[str] = set()
    for b in bases:
        if not b or not os.path.isdir(b):
            continue
        for pat in patterns:
            for p in glob.glob(os.path.join(b, pat), recursive=True):
                if p in seen:
                    continue
                seen.add(p)
                yield p


def _patch_one(path: str) -> bool:
    """Return True if file was modified."""
    try:
        with open(path, "r+b") as f:
            hdr = f.read(64)
            if len(hdr) < 20 or hdr[:4] != b"\x7fELF":
                return False

            elf_class = hdr[4]  # 1=32, 2=64
            elf_data = hdr[5]  # 1=little, 2=big
            if elf_class not in (1, 2) or elf_data not in (1, 2):
                return False
            endian = "<" if elf_data == 1 else ">"

            if elf_class == 2:
                # ELF64
                e_phoff = struct.unpack_from(endian + "Q", hdr, 32)[0]
                e_phentsize = struct.unpack_from(endian + "H", hdr, 54)[0]
                e_phnum = struct.unpack_from(endian + "H", hdr, 56)[0]
                ph_type_off = 0
                ph_flags_off = 4
                ph_min_size = 56
            else:
                # ELF32
                e_phoff = struct.unpack_from(endian + "I", hdr, 28)[0]
                e_phentsize = struct.unpack_from(endian + "H", hdr, 42)[0]
                e_phnum = struct.unpack_from(endian + "H", hdr, 44)[0]
                ph_type_off = 0
                ph_flags_off = 24
                ph_min_size = 32

            if not e_phoff or not e_phentsize or not e_phnum:
                return False
            if e_phentsize < ph_min_size:
                return False

            modified = False
            for i in range(int(e_phnum)):
                ph_off = int(e_phoff + i * e_phentsize)
                f.seek(ph_off)
                ph = f.read(e_phentsize)
                if len(ph) < ph_min_size:
                    break

                p_type = struct.unpack_from(endian + "I", ph, ph_type_off)[0]
                if p_type != PT_GNU_STACK:
                    continue

                p_flags = struct.unpack_from(endian + "I", ph, ph_flags_off)[0]
                if (p_flags & PF_X) == 0:
                    continue

                new_flags = p_flags & (~PF_X)
                f.seek(ph_off + ph_flags_off)
                f.write(struct.pack(endian + "I", new_flags))
                modified = True

            return modified
    except Exception:
        return False


def patch_ctranslate2_execstack() -> None:
    patched: list[str] = []
    for p in _candidate_shared_objects():
        if _patch_one(p):
            patched.append(p)
    if patched:
        logger.warning(
            "Patched execstack flag for ctranslate2 shared objects:\n" + "\n".join(patched)
        )
