#!/usr/bin/env python3
"""Reads files out of Hidden & Dangerous 2 .dta archives (ISD0 and ISD1).

    python dta_read.py ARCHIVE.dta --list [PATTERN]
    python dta_read.py ARCHIVE.dta NAME [NAME...] --out DIR

The key is looked up by the archive's file name (the game's MountDataArchives table) or
given with --key LOW:HIGH. Format: RW_DATA/docs/rw_data_functions.md, sections 3 and 4
(not WAV blocks: those files come out undecoded).
"""
import argparse
import fnmatch
import os
import struct
import sys

KEYS = {
    "patchx03.dta": (0xA0A0A0A4, 0xA0A0A0A0), "patchx02.dta": (0xA0A0A0A3, 0xA0A0A0A0),
    "patchx01.dta": (0xA0A0A0A2, 0xA0A0A0A0), "sabresquadron.dta": (0xA0A0A0A1, 0xA0A0A0A0),
    "langenglish.dta": (0xA0A0A0A0, 0xA0A0A0A0), "patch.dta": (0x5D805270, 0x10ACB252),
    "models.dta": (0x5D805259, 0x10ACB252), "missions.dta": (0x7654A3F0, 0x22BCDA98),
    "maps.dta": (0xB438D0A5, 0xF26527FA), "sounds.dta": (0x4FE85106, 0x8D2965CA),
    "scripts.dta": (0x0AB4E72D, 0xCF761298), "others.dta": (0xEA85902A, 0x65F7AB23),
    "maps_c.dta": (0xB038D0A0, 0xE26520FA), "maps_u.dta": (0xB038D1A1, 0xF26520FA),
}


def xor(data, key):
    k = key * (len(data) // 8 + 1)
    return bytes(a ^ b for a, b in zip(data, k))


def lzss(src):
    """One block: type byte 0 = stored, 1 = LZSS (16-item groups, big-endian flag words)."""
    if not src or src[0] != 1:
        return bytes(src[1:])
    out = bytearray()
    i = 1
    n = len(src)
    while i + 1 < n:
        flags = src[i] << 8 | src[i + 1]
        i += 2
        for _ in range(16):
            if i >= n:
                break
            if flags & 0x8000:
                d = src[i] << 4 | src[i + 1] >> 4
                if d == 0:
                    count = ((src[i + 1] & 0x0F) << 8 | src[i + 2]) + 16
                    out += bytes([src[i + 3]]) * count
                    i += 4
                else:
                    length = (src[i + 1] & 0x0F) + 3
                    start = len(out) - d
                    for j in range(length):
                        out.append(out[start + j])
                    i += 2
            else:
                out.append(src[i])
                i += 1
            flags = flags << 1 & 0xFFFF
    return bytes(out)


class Archive:
    def __init__(self, path, key=None):
        self.path = path
        self.f = open(path, "rb")
        if key is None:
            key = KEYS[os.path.basename(path).lower()]
        self.key = struct.pack("<II", *key)
        magic = self.f.read(4)
        if magic == b"ISD1":
            hdr = xor(self.f.read(20), self.key)
            _, self.table_off, self.table_size, _, _ = struct.unpack("<5I", hdr)
        elif magic == b"ISD0":
            hdr = xor(self.f.read(16), self.key)
            _, self.table_off, self.table_size, _ = struct.unpack("<4I", hdr)
        else:
            raise ValueError("not an archive: %s" % path)
        self.version = magic[3] - 48
        self.f.seek(self.table_off)
        table = xor(self.f.read(self.table_size), self.key)
        self.entries = []
        for o in range(0, len(table), 0x1C):
            h, hdr_off, data_off = struct.unpack_from("<3I", table, o)
            self.entries.append((hdr_off, data_off))
        self.names = {}
        for hdr_off, data_off in self.entries:
            name, info = self._header(hdr_off)
            self.names[name.upper()] = (name, hdr_off, data_off, info)

    def _header(self, off):
        self.f.seek(off)
        h = xor(self.f.read(0x20), self.key)
        size, blocks = struct.unpack_from("<II", h, 0x10)
        nlen = struct.unpack_from("<H", h, 0x1C if self.version == 1 else 0x18)[0]
        encrypted = bool(nlen & 0x8000)
        self.f.seek(off + 0x20)
        name = xor(self.f.read(nlen & 0x7FFF), self.key).split(b"\0")[0].decode("latin1")
        return name, (size, blocks, encrypted, self.f.tell())

    def read(self, name):
        name_, hdr_off, data_off, (size, blocks, encrypted, after_name) = self.names[name.upper()]
        out = bytearray()
        if self.version == 1:
            self.f.seek(after_name)
            sizes = struct.unpack("<%dI" % blocks, self.f.read(4 * blocks))
            types = xor(self.f.read(blocks), self.key)
            for n in range(blocks):
                stored = self.f.read(sizes[n] & 0xFFFF)
                if encrypted:
                    stored = xor(stored, self.key)
                out += lzss(bytes([types[n]]) + stored)
        else:
            self.f.seek(data_off)
            for n in range(blocks):
                word = struct.unpack("<I", self.f.read(4))[0]
                stored = self.f.read(word & 0xFFFF)
                if encrypted:
                    stored = xor(stored, self.key)
                out += lzss(stored)
        if len(out) != size:
            raise ValueError("%s: decoded %d bytes, expected %d" % (name_, len(out), size))
        return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archive")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=".")
    ap.add_argument("--key", help="LOW:HIGH in hex")
    a = ap.parse_args()
    key = tuple(int(x, 16) for x in a.key.split(":")) if a.key else None
    arc = Archive(a.archive, key)
    if a.list:
        pat = a.names[0].upper() if a.names else "*"
        for up, (name, *_rest) in sorted(arc.names.items()):
            if fnmatch.fnmatch(up, pat):
                print(name, _rest[2][0])
        return
    for n in a.names:
        data = arc.read(n)
        dst = os.path.join(a.out, n.replace("\\", os.sep))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        open(dst, "wb").write(data)
        print("%s: %d bytes" % (dst, len(data)))


if __name__ == "__main__":
    sys.exit(main())
