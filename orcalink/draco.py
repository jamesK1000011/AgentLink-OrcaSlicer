# SPDX-License-Identifier: LGPL-2.1-or-later
# Draco (.drc) meshes written and read in plain Python: the bitstream's
# simplest form (version 2.2, sequential connectivity with uncompressed
# indices, positions as raw 32-bit floats through the generic attribute
# coder). No compression, so the files are larger than Draco's own, but any
# Draco decoder reads them — OrcaSlicer's "Export as DRC" without a library.
#
# Written from the Draco bitstream specification (google.github.io/draco/spec).

import struct

MAGIC = b"DRACO"
VERSION = (2, 2)
TRIANGULAR_MESH = 1
MESH_SEQUENTIAL_ENCODING = 0
SEQUENTIAL_UNCOMPRESSED_INDICES = 1
POSITION = 0
DT_FLOAT32 = 9
SEQUENTIAL_ATTRIBUTE_ENCODER_GENERIC = 0


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_varint(data, i):
    result = shift = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return result, i


def _index_writer(num_points):
    if num_points < 256:
        return lambda v: struct.pack("<B", v)
    if num_points < 1 << 16:
        return lambda v: struct.pack("<H", v)
    if num_points < 1 << 21:
        return _varint
    return lambda v: struct.pack("<I", v)


def encode(vertices, faces):
    """A Draco mesh: vertices [(x, y, z)], faces [(a, b, c)] (indices)."""
    if not faces:
        raise ValueError("no triangles to write")
    n = len(vertices)
    out = bytearray(MAGIC)
    out += struct.pack("<BBBBH", VERSION[0], VERSION[1], TRIANGULAR_MESH, MESH_SEQUENTIAL_ENCODING, 0)
    # Connectivity.
    out += _varint(len(faces)) + _varint(n) + struct.pack("<B", SEQUENTIAL_UNCOMPRESSED_INDICES)
    w = _index_writer(n)
    for f in faces:
        for v in f:
            out += w(int(v))
    # Attributes: one decoder holding one attribute, the positions.
    out += struct.pack("<B", 1)
    out += _varint(1)
    out += struct.pack("<BBBB", POSITION, DT_FLOAT32, 3, 0) + _varint(0)
    out += struct.pack("<B", SEQUENTIAL_ATTRIBUTE_ENCODER_GENERIC)
    for x, y, z in vertices:
        out += struct.pack("<fff", x, y, z)
    return bytes(out)


def decode(data):
    """(vertices, faces) of a Draco mesh in the form encode writes — for
    checking our own files; Draco's compressed forms are not read here."""
    if data[:5] != MAGIC:
        raise ValueError("not a Draco file")
    major, minor, etype, method, flags = struct.unpack_from("<BBBBH", data, 5)
    if (etype, method) != (TRIANGULAR_MESH, MESH_SEQUENTIAL_ENCODING) or flags:
        raise ValueError("only sequential, uncompressed Draco meshes are read here")
    i = 11
    nf, i = _read_varint(data, i)
    n, i = _read_varint(data, i)
    if data[i] != SEQUENTIAL_UNCOMPRESSED_INDICES:
        raise ValueError("compressed indices are not read here")
    i += 1
    faces = []
    for _ in range(nf):
        f = []
        for _ in range(3):
            if n < 256:
                v = data[i]
                i += 1
            elif n < 1 << 16:
                v = struct.unpack_from("<H", data, i)[0]
                i += 2
            elif n < 1 << 21:
                v, i = _read_varint(data, i)
            else:
                v = struct.unpack_from("<I", data, i)[0]
                i += 4
            f.append(v)
        faces.append(tuple(f))
    i += 1  # decoders
    _, i = _read_varint(data, i)  # attributes
    att, dt, comps, _norm = struct.unpack_from("<BBBB", data, i)
    i += 4
    _, i = _read_varint(data, i)
    i += 1  # decoder type
    if (att, dt, comps) != (POSITION, DT_FLOAT32, 3):
        raise ValueError("only float positions are read here")
    verts = [struct.unpack_from("<fff", data, i + 12 * k) for k in range(n)]
    return verts, faces
