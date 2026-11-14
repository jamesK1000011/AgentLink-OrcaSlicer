# SPDX-License-Identifier: LGPL-2.1-or-later
# OrcaSlicer headless, with FreeCAD: this package's tools given
# FreeCAD's bodies, faces and kernel — projects made from bodies, painted by
# face, the body changed and its part replaced, letters embossed, meshes
# simplified and joined — one loop between the two: design, slice, read the
# print back, revise the body, re-slice. Loaded by Agent Link for FreeCAD
# (agentlink_families) only; nothing else here imports FreeCAD. Moved from
# Agent Link for FreeCAD's orca family on 14 Nov 2026.

import os

from agentlink.protocol import Tool, ToolError

GROUP = "orca"
INFO = "OrcaSlicer headless (Agent Link for OrcaSlicer): projects from bodies, every setting and part, paint by faces, slice, export, G-code read back."


def _mesh_of(shape, tol=0.01):
    import MeshPart

    m = MeshPart.meshFromShape(Shape=shape, LinearDeflection=tol, AngularDeflection=0.0873, Relative=False)
    pts = [(p.x, p.y, p.z) for p in m.Points]
    return [[pts[a], pts[b], pts[c]] for a, b, c in m.Topology[1]]


def geo_for(session, base):
    """FreeCAD's side of the loop, as orcalink's Geo."""
    s = session

    class FreeCADGeo(base):
        name = "FreeCAD"

        def body(self, name):
            if name is None:
                raise ToolError("invalid_input", "body: a FreeCAD body.")
            return s.body(name)

        @staticmethod
        def label(b):
            return b.Label

        @staticmethod
        def tris(b, tol=0.01):
            return _mesh_of(b.Shape, tol)

        @staticmethod
        def bbox(b):
            bb = b.Shape.BoundBox
            return [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]

        @staticmethod
        def shape(b):
            return b.Shape

        @staticmethod
        def face_normal(b, face):
            f = b.Shape.Faces[int(str(face).replace("Face", "")) - 1]
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            return [n.x, n.y, n.z]

        @staticmethod
        def face_of(b, points):
            """The face nearest each point: the faces whose (slightly grown)
            boxes hold it are measured exactly."""
            import FreeCAD
            import Part

            shape = b.Shape
            tol = max(shape.BoundBox.DiagonalLength * 1e-3, 0.05)
            boxes = []
            for f in shape.Faces:
                bb = f.BoundBox
                boxes.append((bb.XMin - tol, bb.YMin - tol, bb.ZMin - tol, bb.XMax + tol, bb.YMax + tol, bb.ZMax + tol))
            out = []
            for c in points:
                cand = [fi for fi, bx in enumerate(boxes) if bx[0] <= c[0] <= bx[3] and bx[1] <= c[1] <= bx[4] and bx[2] <= c[2] <= bx[5]]
                if len(cand) <= 1:
                    out.append(cand[0] if cand else None)
                    continue
                v = Part.Vertex(FreeCAD.Vector(*c))
                out.append(min(cand, key=lambda fi: shape.Faces[fi].distToShape(v)[0]))
            return out

        @staticmethod
        def presets(label, work):
            from addonkit import records as store

            from . import presets as SP
            from addonkit.materials import DENSITY

            setup = (store.setup_of(s.doc, label, "print") if label else None) or {}
            settings = {k: v for k, v in setup.items() if k not in ("id", "name", "type", "bodies")}
            mat = (store.materials(s.doc).get(label) if label else None) or "pla"
            settings["filament"], settings["density"] = mat.split("-")[0], DENSITY.get(mat, 1.24)
            chosen = setup.get("slicerPresets")
            profiles = {}
            if chosen:
                data = SP.load_saved(s.out_dir, chosen["bundle"]) if chosen.get("bundle") else SP.bundle(chosen.get("slicer", "orcaslicer"), chosen["machine"], chosen["process"], chosen["filament"])
                profiles = SP.write_profiles(data, os.path.join(work, "presets"))
            return settings, profiles

        @staticmethod
        def emboss(text=None, svg=None, font=None, size=None, depth=1.0, rotate=None, at=(0, 0, 0)):
            import FreeCAD
            import Part

            if text:
                wires = Part.makeWireString(str(text), font, float(size or 8), 0)
                faces = []
                for ch in wires:
                    ws = [w for w in ch if w.isClosed()]
                    if ws:
                        try:
                            faces.append(Part.Face(ws, "Part::FaceMakerBullseye"))
                        except Exception:
                            faces += [Part.Face(w) for w in ws]
                if not faces:
                    raise ToolError("failed", "The text gave no closed outlines.")
                flat = Part.makeCompound(faces)
            else:
                import importSVG

                doc = FreeCAD.newDocument("agentlink_svg")
                try:
                    importSVG.insert(svg, doc.Name)
                    ws = [w for ob in doc.Objects if hasattr(ob, "Shape") for w in ob.Shape.Wires if w.isClosed()]
                    flat = Part.makeCompound([Part.Face(w) for w in ws])
                    if size:
                        bb = flat.BoundBox
                        flat = flat.scale(float(size) / max(bb.XLength, bb.YLength, 1e-6))
                finally:
                    FreeCAD.closeDocument(doc.Name)
            solid = flat.extrude(FreeCAD.Vector(0, 0, depth))
            bb = solid.BoundBox
            solid.translate(FreeCAD.Vector(-(bb.XMin + bb.XMax) / 2, -(bb.YMin + bb.YMax) / 2, 0))
            for axis, deg in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotate or ()):
                if deg:
                    solid.rotate(FreeCAD.Vector(), FreeCAD.Vector(*axis), deg)
            solid.translate(FreeCAD.Vector(*at))
            return _mesh_of(solid, 0.02)

        @staticmethod
        def mesh(op, tris, a):
            """FreeCAD's Mesh module where it does more than plain Python:
            simplify, fix, smooth, boolean."""
            if op not in ("simplify", "fix", "smooth", "boolean"):
                return None
            import Mesh

            m = Mesh.Mesh(tris)
            if op == "simplify":
                m.decimate(float(a.get("tolerance", 0.05)), float(a.get("ratio", 0.5)))
            elif op == "fix":
                m.harmonizeNormals()
                m.removeDuplicatedPoints()
                m.removeDuplicatedFacets()
                m.fixDegenerations(1e-6)
                m.fixSelfIntersections()
                m.fillupHoles(1000)
            elif op == "smooth":
                m.smooth(int(a.get("iterations", 3)))
            else:
                om = Mesh.Mesh(a["_with"])
                m = {"union": m.unite, "difference": m.difference, "intersection": m.intersect}[a.get("mode", "difference")](om)
            pts = [(q.x, q.y, q.z) for q in m.Points]
            return [[pts[i], pts[j], pts[k]] for i, j, k in m.Topology[1]]

        @staticmethod
        def capper(loops, z):
            """A cut's outlines made one flat face (holes kept) by FreeCAD and
            tessellated: light on the kernel, only flat faces go through it."""
            try:
                import FreeCAD
                import Part
            except ImportError:
                return None

            wires = []
            for lp in loops:
                try:
                    wires.append(Part.makePolygon([FreeCAD.Vector(p[0], p[1], z) for p in lp] + [FreeCAD.Vector(lp[0][0], lp[0][1], z)]))
                except Exception:  # noqa: BLE001 — a degenerate loop
                    pass
            if not wires:
                return None
            try:
                face = Part.Face(wires, "Part::FaceMakerBullseye")
                pts, ft = face.tessellate(0.05)
            except Exception:  # noqa: BLE001 — the plain ear clipping does it
                return None
            return [((pts[i].x, pts[i].y), (pts[j].x, pts[j].y), (pts[k].x, pts[k].y)) for i, j, k in ft]

    return FreeCADGeo()


def tools(session):
    from . import tools as OT
    from .protocol import ToolError as OrcaError

    made = OT.tools(lambda: session.out_dir, geo_for(session, OT.Geo))

    def wrap(fn):
        # orcalink's refusals become Agent Link's (the same code and message).
        def call(a):
            try:
                return fn(a)
            except OrcaError as e:
                raise ToolError(e.code, e.message)

        return call

    out = []
    for t in made:
        desc = t.description.replace("orca_paint paints it", "orca_paint paints it (by FreeCAD face)")
        out.append(Tool(t.name, desc, t.schema, wrap(t.fn), changes=t.changes))
    return out
