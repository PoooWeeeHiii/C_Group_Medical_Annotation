"""Build teaching-demo robot path plans from simulated-surgery ROI geometry.

Coordinate chain (documented in docs/19_robot_path_coord_convention.md):
  UVW[0,1] → IJK → Patient_LPS(mm) → Patient_RAS(mm) → RobotBase (simulated rigid)
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0.0"
DEFAULT_APPROACH_OFFSET_MM = 10.0
DEFAULT_TOOL_MODEL = "demo_scalpel_v1"
DEFAULT_BLADE_TYPE = "virtual_plane_blade"
CALIBRATION_VERSION = os.environ.get("ROBOT_CALIBRATION_VERSION", "sim-calib-v1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _vec3(values: Any, default: list[float] | None = None) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        return list(default or [0.0, 0.0, 0.0])
    return [float(values[0]), float(values[1]), float(values[2])]


def _norm(v: list[float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _normalize(v: list[float]) -> list[float]:
    n = _norm(v)
    if n < 1e-12:
        return [0.0, 0.0, 1.0]
    return [v[0] / n, v[1] / n, v[2] / n]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _add(a: list[float], b: list[float]) -> list[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _scale(a: list[float], s: float) -> list[float]:
    return [a[0] * s, a[1] * s, a[2] * s]


def _matmul3(m: list[float], v: list[float]) -> list[float]:
    """Apply row-major 3x3 (ITK direction) to vector."""
    return [
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    ]


def _looks_like_uvw(points: list[list[float]]) -> bool:
    if not points:
        return True
    return all(-0.05 <= c <= 1.05 for p in points for c in p[:3])


def uvw_to_ijk(uvw: list[float], shape_xyz: tuple[int, int, int]) -> list[float]:
    nx, ny, nz = shape_xyz
    return [
        float(uvw[0]) * max(nx - 1, 1),
        float(uvw[1]) * max(ny - 1, 1),
        float(uvw[2]) * max(nz - 1, 1),
    ]


def ijk_to_lps(
    ijk: list[float],
    spacing: list[float],
    origin: list[float],
    direction: list[float],
) -> list[float]:
    scaled = [ijk[0] * spacing[0], ijk[1] * spacing[1], ijk[2] * spacing[2]]
    offset = _matmul3(direction, scaled)
    return _add(origin, offset)


def lps_to_ras(lps: list[float]) -> list[float]:
    """DICOM LPS → RAS via diag(-1, -1, 1)."""
    return [-lps[0], -lps[1], lps[2]]


def point_to_frames(
    raw: list[float],
    *,
    as_uvw: bool,
    shape_xyz: tuple[int, int, int],
    spacing: list[float],
    origin: list[float],
    direction: list[float],
    t_robot_from_lps: list[list[float]],
) -> dict[str, Any]:
    if as_uvw:
        ijk = uvw_to_ijk(raw, shape_xyz)
        uvw = [float(raw[0]), float(raw[1]), float(raw[2])]
    else:
        ijk = [float(raw[0]), float(raw[1]), float(raw[2])]
        nx, ny, nz = shape_xyz
        uvw = [
            ijk[0] / max(nx - 1, 1),
            ijk[1] / max(ny - 1, 1),
            ijk[2] / max(nz - 1, 1),
        ]
    lps = ijk_to_lps(ijk, spacing, origin, direction)
    ras = lps_to_ras(lps)
    robot = _apply_rigid(t_robot_from_lps, lps)
    return {
        "uvw": [round(v, 6) for v in uvw],
        "ijk": [round(v, 4) for v in ijk],
        "lps_mm": [round(v, 4) for v in lps],
        "ras_mm": [round(v, 4) for v in ras],
        "robot_mm": [round(v, 4) for v in robot],
        "frame": "patient_lps",
    }


def _identity4() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _parse_transform_env() -> list[list[float]]:
    raw = (os.environ.get("ROBOT_T_LPS") or "").strip()
    if not raw:
        return _identity4()
    try:
        vals = [float(x) for x in raw.replace(",", " ").split()]
        if len(vals) == 16:
            return [vals[0:4], vals[4:8], vals[8:12], vals[12:16]]
    except ValueError:
        pass
    return _identity4()


def _apply_rigid(t: list[list[float]], p: list[float]) -> list[float]:
    x = t[0][0] * p[0] + t[0][1] * p[1] + t[0][2] * p[2] + t[0][3]
    y = t[1][0] * p[0] + t[1][1] * p[1] + t[1][2] * p[2] + t[1][3]
    z = t[2][0] * p[0] + t[2][1] * p[1] + t[2][2] * p[2] + t[2][3]
    return [x, y, z]


def affine_from_sitk(
    spacing: list[float],
    origin: list[float],
    direction: list[float],
) -> list[list[float]]:
    """4x4 affine mapping IJK index → LPS mm (homogeneous columns)."""
    d = direction if len(direction) >= 9 else [1, 0, 0, 0, 1, 0, 0, 0, 1]
    # columns = direction * spacing
    c0 = _matmul3(d, [spacing[0], 0, 0])
    c1 = _matmul3(d, [0, spacing[1], 0])
    c2 = _matmul3(d, [0, 0, spacing[2]])
    return [
        [c0[0], c1[0], c2[0], origin[0]],
        [c0[1], c1[1], c2[1], origin[1]],
        [c0[2], c1[2], c2[2], origin[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def rotation_matrix_to_quat(r: list[list[float]]) -> list[float]:
    """Return quaternion [x, y, z, w] from 3x3 rotation (rows)."""
    m00, m01, m02 = r[0]
    m10, m11, m12 = r[1]
    m20, m21, m22 = r[2]
    trace = m00 + m11 + m22
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m21 - m12) * s
        y = (m02 - m20) * s
        z = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return [round(x / n, 6), round(y / n, 6), round(z / n, 6), round(w / n, 6)]


def tcp_orientation_from_plane(
    normal: list[float],
    polygon: list[list[float]],
    keep_sign: int,
) -> tuple[list[list[float]], list[float]]:
    """Tool Z along cut normal toward resected side; X along first polygon edge."""
    z_axis = _normalize(_scale(normal, float(keep_sign or 1) * -1.0))
    # keepSign marks kept half-space; resected side is opposite → approach along -keepSign * normal
    # Actually: carve removes side where (p-o)·n has opposite sign to keepSign.
    # Tool Z points into tissue being cut → opposite of keep half-space normal direction.
    z_axis = _normalize(_scale(normal, -float(keep_sign or 1)))
    if len(polygon) >= 2:
        edge = _sub(polygon[1], polygon[0])
        x_axis = _normalize(_sub(edge, _scale(z_axis, _dot(edge, z_axis))))
    else:
        ref = [1.0, 0.0, 0.0] if abs(z_axis[0]) < 0.9 else [0.0, 1.0, 0.0]
        x_axis = _normalize(_cross(ref, z_axis))
    y_axis = _normalize(_cross(z_axis, x_axis))
    x_axis = _normalize(_cross(y_axis, z_axis))
    # columns are tool axes in LPS
    r = [
        [x_axis[0], y_axis[0], z_axis[0]],
        [x_axis[1], y_axis[1], z_axis[1]],
        [x_axis[2], y_axis[2], z_axis[2]],
    ]
    return r, rotation_matrix_to_quat(r)


def plane_cuboid_intersection_uvw(
    origin: list[float],
    normal: list[float],
    cuboid_min: list[float],
    cuboid_max: list[float],
) -> list[list[float]]:
    corners = []
    for x in (cuboid_min[0], cuboid_max[0]):
        for y in (cuboid_min[1], cuboid_max[1]):
            for z in (cuboid_min[2], cuboid_max[2]):
                corners.append([x, y, z])
    edges = [
        (0, 1), (2, 3), (4, 5), (6, 7),
        (0, 2), (1, 3), (4, 6), (5, 7),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    hits: list[list[float]] = []
    ox, oy, oz = origin
    nx, ny, nz = normal
    for ia, ib in edges:
        a, b = corners[ia], corners[ib]
        da = (a[0] - ox) * nx + (a[1] - oy) * ny + (a[2] - oz) * nz
        db = (b[0] - ox) * nx + (b[1] - oy) * ny + (b[2] - oz) * nz
        if da * db > 0:
            continue
        if abs(da - db) < 1e-12:
            continue
        t = da / (da - db)
        if t < -1e-4 or t > 1 + 1e-4:
            continue
        hits.append(
            [
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
            ]
        )
    unique: list[list[float]] = []
    for p in hits:
        if any(_norm(_sub(p, q)) < 1e-4 for q in unique):
            continue
        unique.append(p)
    if len(unique) < 3:
        return unique
    cx = sum(p[0] for p in unique) / len(unique)
    cy = sum(p[1] for p in unique) / len(unique)
    cz = sum(p[2] for p in unique) / len(unique)
    ax = [1.0, 0.0, 0.0] if abs(nx) < 0.9 else [0.0, 1.0, 0.0]
    ux = _normalize(_cross(ax, [nx, ny, nz]))
    uy = _normalize(_cross([nx, ny, nz], ux))

    def angle(p: list[float]) -> float:
        d = _sub(p, [cx, cy, cz])
        return math.atan2(_dot(d, uy), _dot(d, ux))

    unique.sort(key=angle)
    return unique


def _load_volume_meta(image_id: str) -> dict[str, Any] | None:
    try:
        from backend.app.services.medical_image_service import get_volume_metadata

        return get_volume_metadata(image_id)
    except Exception:
        return None


def build_robot_plan(
    *,
    image_id: str,
    case_id: str,
    mask_id: str | None,
    label_id: int,
    organ: dict[str, Any] | None,
    cuboid_min: list[float],
    cuboid_max: list[float],
    cut_planes: list[dict[str, Any]],
    knife_radius: int = 2,
    carved_voxels: int = 0,
    result_id: str | None = None,
    cut_timestamps: list[dict[str, Any]] | None = None,
    overrides: dict[str, Any] | None = None,
    volume_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble full robot_plan dict. Never raises for missing volume — marks incomplete."""
    overrides = dict(overrides or {})
    server_meta = _load_volume_meta(image_id) or {}
    client_meta = volume_meta if isinstance(volume_meta, dict) else {}
    # Prefer full-resolution image metadata from disk; fill gaps from client cache.
    meta = {**client_meta, **{k: v for k, v in server_meta.items() if v is not None}}
    if not server_meta:
        meta = dict(client_meta)

    spacing = _vec3(meta.get("spacing"), [1.0, 1.0, 1.0])
    origin = _vec3(meta.get("origin"), [0.0, 0.0, 0.0])
    direction_raw = meta.get("direction")
    if isinstance(direction_raw, (list, tuple)) and len(direction_raw) >= 9:
        direction = [float(v) for v in direction_raw[:9]]
    else:
        direction = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    depth = int(meta.get("slice_count") or meta.get("depth") or 0)
    has_shape = width > 0 and height > 0 and depth > 0
    shape_xyz = (width, height, depth) if has_shape else (1, 1, 1)

    sample_pts = [cuboid_min, cuboid_max]
    for plane in cut_planes or []:
        sample_pts.append(_vec3(plane.get("origin")))
        for p in plane.get("polygon") or []:
            sample_pts.append(_vec3(p))
    as_uvw = _looks_like_uvw(sample_pts)

    status = "ok"
    warnings: list[str] = []
    if not meta.get("spacing") or not has_shape:
        status = "incomplete"
        warnings.append("volume metadata missing or incomplete; using unit spacing/identity")

    t_robot = _parse_transform_env()
    affine = affine_from_sitk(spacing, origin, direction)
    registered_at = _now_iso()

    def map_pt(raw: list[float]) -> dict[str, Any]:
        return point_to_frames(
            raw,
            as_uvw=as_uvw,
            shape_xyz=shape_xyz,
            spacing=spacing,
            origin=origin,
            direction=direction,
            t_robot_from_lps=t_robot,
        )

    cuboid_lps_min = map_pt(cuboid_min)["lps_mm"]
    cuboid_lps_max = map_pt(cuboid_max)["lps_mm"]
    # Ensure AABB ordering in LPS
    aabb_min = [min(cuboid_lps_min[i], cuboid_lps_max[i]) for i in range(3)]
    aabb_max = [max(cuboid_lps_min[i], cuboid_lps_max[i]) for i in range(3)]

    min_spacing = min(abs(s) for s in spacing) or 1.0
    thickness_mm = float(overrides.get("thickness_mm") or (0.5 + float(knife_radius) * min_spacing))
    approach_mm = float(overrides.get("approach_offset_mm") or DEFAULT_APPROACH_OFFSET_MM)
    v_max = float(overrides.get("v_max_mm_s") or 20.0)
    a_max = float(overrides.get("a_max_mm_s2") or 50.0)
    force_limit = float(overrides.get("force_limit_n") or 5.0)
    tool_model = str(overrides.get("tool_model") or DEFAULT_TOOL_MODEL)
    blade_type = str(overrides.get("blade_type") or DEFAULT_BLADE_TYPE)

    tool_paths: list[dict[str, Any]] = []
    for idx, plane in enumerate(cut_planes or []):
        origin_u = _vec3(plane.get("origin"))
        normal_u = _normalize(_vec3(plane.get("normal"), [0, 0, 1]))
        keep_sign = int(plane.get("keepSign", plane.get("keep_sign", 1)) or 1)
        polygon_u = [_vec3(p) for p in (plane.get("polygon") or []) if isinstance(p, (list, tuple))]
        if len(polygon_u) < 3:
            polygon_u = plane_cuboid_intersection_uvw(origin_u, normal_u, cuboid_min, cuboid_max)

        mapped_poly = [map_pt(p) for p in polygon_u]
        poly_lps = [m["lps_mm"] for m in mapped_poly]
        # Map normal to LPS (direction only — ignore translation)
        n_ijk = normal_u if not as_uvw else [
            normal_u[0] * max(shape_xyz[0] - 1, 1),
            normal_u[1] * max(shape_xyz[1] - 1, 1),
            normal_u[2] * max(shape_xyz[2] - 1, 1),
        ]
        # Differential: LPS direction of unit IJK step along normal components
        n_lps = _normalize(
            _matmul3(
                direction,
                [n_ijk[0] * spacing[0], n_ijk[1] * spacing[1], n_ijk[2] * spacing[2]],
            )
        )

        if len(poly_lps) < 1:
            warnings.append(f"cut_plane[{idx}] has no usable polygon; skipped path geometry")
            continue

        rot, quat = tcp_orientation_from_plane(n_lps, poly_lps, keep_sign)
        approach_dir = _normalize(_scale(n_lps, -float(keep_sign)))
        # Entry: first vertex lifted along approach
        entry_lps = _add(poly_lps[0], _scale(approach_dir, approach_mm))
        exit_lps = _add(poly_lps[-1], _scale(approach_dir, approach_mm))

        def pose_at(lps: list[float]) -> dict[str, Any]:
            ras = lps_to_ras(lps)
            robot = _apply_rigid(t_robot, lps)
            return {
                "position_lps_mm": [round(v, 4) for v in lps],
                "position_ras_mm": [round(v, 4) for v in ras],
                "position_robot_mm": [round(v, 4) for v in robot],
                "orientation_quat_xyzw": quat,
                "orientation_matrix_lps": [[round(c, 6) for c in row] for row in rot],
                "frame": "patient_lps",
            }

        waypoints = [pose_at(p) for p in poly_lps]
        # Depth ≈ distance across ROI along tool Z
        depth_mm = abs(_dot(_sub(aabb_max, aabb_min), n_lps))
        ts = None
        if cut_timestamps and idx < len(cut_timestamps):
            ts = cut_timestamps[idx]

        tool_paths.append(
            {
                "cut_index": idx,
                "order": idx + 1,
                "multi_pass": False,
                "approach_offset_mm": approach_mm,
                "depth_mm": round(depth_mm, 4),
                "thickness_mm": round(thickness_mm, 4),
                "entry": pose_at(entry_lps),
                "waypoints": waypoints,
                "exit": pose_at(exit_lps),
                "constraints": {
                    "v_max_mm_s": v_max,
                    "a_max_mm_s2": a_max,
                    "force_limit_n": force_limit,
                    "status": "placeholder",
                    "note": "Teaching defaults; replace before real robot use",
                },
                "plane_uvw": {
                    "origin": origin_u,
                    "normal": normal_u,
                    "keepSign": keep_sign,
                },
                "started_at": (ts or {}).get("started_at"),
                "ended_at": (ts or {}).get("ended_at"),
            }
        )

    surface_mesh_url = None
    if mask_id:
        surface_mesh_url = f"/api/mask/{mask_id}/surface-mesh"

    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "warnings": warnings,
        "unit": "mm",
        "disclaimer": (
            "Teaching / research demo only. Not for clinical navigation or robot control."
        ),
        "result_id": result_id,
        "case_id": case_id,
        "image_id": image_id,
        "coordinate_frames": {
            "input_space": "uvw_normalized_0_1" if as_uvw else "ijk_continuous",
            "primary": "patient_lps",
            "also_stored": ["patient_ras", "robot_base"],
            "unit": "mm",
            "spacing_mm": spacing,
            "origin_lps_mm": origin,
            "direction_3x3_row_major": direction,
            "affine_ijk_to_lps_4x4": affine,
            "shape_xyz": list(shape_xyz),
            "lps_to_ras": {
                "matrix_diag": [-1.0, -1.0, 1.0],
                "note": "RAS = [-LPS_x, -LPS_y, LPS_z]",
            },
            "docs": "docs/19_robot_path_coord_convention.md",
        },
        "registration": {
            "type": "simulated_rigid",
            "status": "placeholder" if t_robot == _identity4() else "configured",
            "T_robot_from_lps_4x4": t_robot,
            "calibration_version": CALIBRATION_VERSION,
            "registered_at": registered_at,
            "note": (
                "Default identity. Override with env ROBOT_T_LPS (16 floats) "
                "or replace after real OR registration."
            ),
        },
        "tool_paths": tool_paths,
        "anatomy_safety": {
            "roi_aabb_lps_mm": {"min": aabb_min, "max": aabb_max},
            "roi_aabb_ras_mm": {
                "min": lps_to_ras(aabb_min),
                "max": lps_to_ras(aabb_max),
            },
            "organ": organ or {"label_id": label_id},
            "organ_surface_mesh": {
                "status": "reference" if mask_id else "unavailable",
                "mask_id": mask_id,
                "label_id": label_id,
                "url": surface_mesh_url,
                "note": "Fetch mesh separately; coordinates follow platform surface-mesh convention",
            },
            "keep_out": {
                "status": "placeholder",
                "structures": [],
                "min_distance_mm": float(overrides.get("keep_out_min_distance_mm") or 3.0),
                "note": "Populate vessel/nerve ROIs when available",
            },
            "ports": {
                "status": "placeholder",
                "incision_points_lps_mm": [],
                "note": "Set laparoscopic/robot port locations in LPS mm",
            },
            "joint_limits": {
                "status": "placeholder",
                "note": "Robot-specific; not computed in this demo",
            },
            "collision": {
                "status": "placeholder",
                "bodies": ["patient", "table", "instrument"],
                "note": "Replace with real collision meshes before execution",
            },
        },
        "repro_meta": {
            "cut_order": [p["order"] for p in tool_paths],
            "cut_count": len(tool_paths),
            "carved_voxels": carved_voxels,
            "knife_radius_ui": knife_radius,
            "tool_model": tool_model,
            "blade_type": blade_type,
            "mask_id": mask_id,
            "calibration_version": CALIBRATION_VERSION,
            "created_at": registered_at,
            "coord_convention_doc": "docs/19_robot_path_coord_convention.md",
        },
    }
    return plan


def rebuild_robot_plan_from_record(record: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild plan from a SurgeryResultRecord or dict-like row."""
    if hasattr(record, "model_dump"):
        data = record.model_dump()
    else:
        data = dict(record)
    return build_robot_plan(
        image_id=str(data["image_id"]),
        case_id=str(data["case_id"]),
        mask_id=data.get("mask_id"),
        label_id=int(data["label_id"]),
        organ=data.get("organ"),
        cuboid_min=list(data.get("cuboid_min") or [0, 0, 0]),
        cuboid_max=list(data.get("cuboid_max") or [1, 1, 1]),
        cut_planes=list(data.get("cut_planes") or []),
        knife_radius=int(data.get("knife_radius") or 2),
        carved_voxels=int(data.get("carved_voxels") or 0),
        result_id=str(data.get("result_id") or ""),
        overrides=overrides,
    )
