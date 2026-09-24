"""Build the small, self-contained fixed-wing glTF used on the Earth page.

Run with: python tools/build_aircraft_model.py
Local coordinates are east, north (nose), up; glTF stores them as X, Y, Z
with its Y-up convention, so Cesium places the nose along local north.
"""

import json
import math
import struct
from pathlib import Path


OUT = Path(__file__).resolve().parents[1] / "src/earth/assets/fixed-wing.glb"
MATERIALS = [
    ("shell", [0.91, 0.96, 1.0, 1.0]),
    ("wing", [0.78, 0.88, 0.98, 1.0]),
    ("underside", [0.35, 0.49, 0.61, 1.0]),
    ("canopy", [0.09, 0.21, 0.30, 1.0]),
    ("wingtip", [0.23, 0.38, 0.54, 1.0]),
]
triangles = [[] for _ in MATERIALS]


def triangle(material, a, b, c):
    """Add one flat-shaded triangle in local east/north/up coordinates."""
    ux, uy, uz = (b[i] - a[i] for i in range(3))
    vx, vy, vz = (c[i] - a[i] for i in range(3))
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return
    # Convert ENU into glTF's Y-up basis: east X, up Y, south Z.
    normal = (nx / length, nz / length, -ny / length)
    for x, y, z in (a, b, c):
        triangles[material].append(((x, z, -y), normal))


def face(material, vertices):
    for index in range(1, len(vertices) - 1):
        triangle(material, vertices[0], vertices[index], vertices[index + 1])


def plate(outline, bottom, top, upper=1, lower=2, sides=2):
    top_ring = [(x, y, top) for x, y in outline]
    bottom_ring = [(x, y, bottom) for x, y in outline]
    face(upper, top_ring)
    face(lower, list(reversed(bottom_ring)))
    for index in range(len(outline)):
        next_index = (index + 1) % len(outline)
        face(sides, [bottom_ring[index], bottom_ring[next_index],
                     top_ring[next_index], top_ring[index]])


# Main wing, swept back toward the tips, plus darker tip caps.
for side in (-1, 1):
    plate([(side * 0.13, 0.65), (side * 2.35, -0.12),
           (side * 2.30, -0.48), (side * 0.15, -0.46)], 0.09, 0.20)
    plate([(side * 1.98, -0.02), (side * 2.35, -0.12),
           (side * 2.30, -0.48), (side * 1.98, -0.47)], 0.205, 0.212,
          upper=4, lower=4, sides=4)
    plate([(side * 0.12, -1.23), (side * 0.98, -1.36),
           (side * 0.98, -1.62), (side * 0.10, -1.55)], 0.11, 0.19)

# Fuselage: six tapered stations, with a distinct upper and lower facet.
stations = [
    (-1.72, 0.04, 0.15, 0.22),
    (-1.36, 0.12, 0.08, 0.31),
    (-0.55, 0.17, 0.04, 0.34),
    (0.55, 0.24, 0.02, 0.38),
    (1.26, 0.17, 0.08, 0.33),
    (1.74, 0.00, 0.19, 0.21),
]
for index in range(len(stations) - 1):
    y0, w0, low0, high0 = stations[index]
    y1, w1, low1, high1 = stations[index + 1]
    face(0, [(-w0, y0, high0), (w0, y0, high0),
             (w1, y1, high1), (-w1, y1, high1)])
    face(2, [(-w0, y0, low0), (-w1, y1, low1),
             (w1, y1, low1), (w0, y0, low0)])
    for side in (-1, 1):
        face(0, [(side * w0, y0, low0), (side * w1, y1, low1),
                 (side * w1, y1, high1), (side * w0, y0, high0)])

# Dark cockpit, raised dorsal fin, and a small nose cap.
face(3, [(-0.14, 0.52, 0.387), (0.14, 0.52, 0.387),
         (0.12, 1.13, 0.355), (-0.12, 1.13, 0.355)])
for side in (-1, 1):
    face(0, [(side * 0.045, -1.58, 0.25),
             (side * 0.045, -1.33, 0.84),
             (side * 0.045, -0.93, 0.31)])
face(4, [(-0.07, 1.52, 0.22), (0.07, 1.52, 0.22),
         (0.0, 1.76, 0.20)])

blob = bytearray()
buffer_views = []
accessors = []
primitives = []
for material, vertices in enumerate(triangles):
    if not vertices:
        continue
    offset = len(blob)
    for position, normal in vertices:
        blob.extend(struct.pack("<6f", *position, *normal))
    buffer_views.append({"buffer": 0, "byteOffset": offset,
                         "byteLength": len(blob) - offset, "byteStride": 24,
                         "target": 34962})
    view = len(buffer_views) - 1
    positions = [entry[0] for entry in vertices]
    accessors.extend([
        {"bufferView": view, "componentType": 5126, "count": len(vertices),
         "type": "VEC3", "byteOffset": 0,
         "min": [min(p[i] for p in positions) for i in range(3)],
         "max": [max(p[i] for p in positions) for i in range(3)]},
        {"bufferView": view, "componentType": 5126, "count": len(vertices),
         "type": "VEC3", "byteOffset": 12},
    ])
    primitives.append({"attributes": {"POSITION": len(accessors) - 2,
                                       "NORMAL": len(accessors) - 1},
                       "material": material, "mode": 4})

document = {
    "asset": {"version": "2.0", "generator": "build_aircraft_model.py"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0}],
    "meshes": [{"name": "fixed-wing-drone", "primitives": primitives}],
    "materials": [{"name": name, "doubleSided": True,
                   "pbrMetallicRoughness": {"baseColorFactor": color,
                                            "metallicFactor": 0.08,
                                            "roughnessFactor": 0.66}}
                  for name, color in MATERIALS],
    "buffers": [{"byteLength": len(blob)}],
    "bufferViews": buffer_views,
    "accessors": accessors,
}
json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
json_chunk += b" " * (-len(json_chunk) % 4)
blob.extend(b"\x00" * (-len(blob) % 4))
size = 12 + 8 + len(json_chunk) + 8 + len(blob)
OUT.write_bytes(struct.pack("<4sII", b"glTF", 2, size)
                + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
                + struct.pack("<I4s", len(blob), b"BIN\x00") + blob)
print(f"Wrote {OUT} ({size} bytes)")
