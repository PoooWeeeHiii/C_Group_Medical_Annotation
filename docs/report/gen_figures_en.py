#!/usr/bin/env python3
"""Generate English-only figures for the EN internship report."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Ellipse
from pathlib import Path

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False

FIG_DIR = Path(__file__).resolve().parent / "figures" / "en"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def save(fig, name: str) -> None:
    fig.savefig(FIG_DIR / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


def box(ax, x, y, w, h, fc, text, fs=9):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.03,rounding_size=0.08",
            facecolor=fc,
            edgecolor="#334",
            linewidth=1.2,
        )
    )
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


# Fig1 architecture
fig, ax = plt.subplots(figsize=(11, 6.2))
ax.set_xlim(0, 11)
ax.set_ylim(0, 6.5)
ax.axis("off")
ax.set_title("Fig. 1  Overall Architecture of the Medical Annotation Platform", fontsize=13, pad=12)
layers = [
    (0.4, 5.2, 10.2, 1.0, "#E8F1FA", "Presentation\nFrontend (app.js / volume_viewer.js / hand_gesture.js) · React web · VTK / WebGL2 / MediaPipe"),
    (0.4, 3.7, 10.2, 1.0, "#EAF6EA", "API Layer\nFastAPI /api/* · Auth JWT · Cases/Images/Masks/Versions · AI Predict · Surgery Results · Export"),
    (0.4, 2.2, 4.8, 1.0, "#FFF6E5", "Business Services\nmask / volume / workflow\nsurgery / ai_service"),
    (5.6, 2.2, 5.0, 1.0, "#F5EAF6", "AI Integration\nnnU-Net / TotalSeg / DeepEdit\nplatform_unet predict"),
    (0.4, 0.7, 4.8, 1.0, "#F0F0F0", "Data Layer\nSQLite · schema.sql\nsurgery_results / masks"),
    (5.6, 0.7, 5.0, 1.0, "#F0F0F0", "Storage\ndataset/ · DICOM/NIfTI\nmask files & exported Dataset"),
]
for args in layers:
    box(ax, *args, fs=8.5)
save(fig, "fig1_architecture.png")

# Fig2 usecase
fig, ax = plt.subplots(figsize=(10, 6.5))
ax.set_xlim(0, 10)
ax.set_ylim(0, 7)
ax.axis("off")
ax.set_title("Fig. 2  Core Use Cases (Platform Side)", fontsize=13, pad=10)
for name, y in [("Annotator", 5.5), ("Reviewer", 3.5), ("Admin", 1.5)]:
    ax.add_patch(Ellipse((1.2, y), 1.6, 0.9, facecolor="#DDEEFF", edgecolor="#234"))
    ax.text(1.2, y, name, ha="center", va="center", fontsize=8)
ax.add_patch(Rectangle((3.0, 0.4), 6.5, 6.2, fill=False, edgecolor="#234", linewidth=1.5))
ax.text(6.25, 6.35, "Medical Annotation Platform", ha="center", fontsize=10, fontweight="bold")
usecases = [
    (5.0, 5.8, "Login & RBAC"),
    (7.6, 5.8, "Upload CT / DICOM"),
    (5.0, 4.7, "2D multi-label edit"),
    (7.6, 4.7, "Version save/compare"),
    (5.0, 3.6, "3D / MPR view"),
    (7.6, 3.6, "Gesture organ pick"),
    (5.0, 2.5, "AI predict"),
    (7.6, 2.5, "Surgery ROI save"),
    (5.0, 1.4, "Task & review"),
    (7.6, 1.4, "Export Dataset"),
]
for x, y, t in usecases:
    ax.add_patch(Ellipse((x, y), 2.2, 0.7, facecolor="#FFF8E7", edgecolor="#444"))
    ax.text(x, y, t, ha="center", va="center", fontsize=7.5)
for y in [5.5, 3.5, 1.5]:
    ax.annotate("", xy=(3.9, min(y, 5.8)), xytext=(2.0, y), arrowprops=dict(arrowstyle="-", color="#666", lw=0.8))
save(fig, "fig2_usecase.png")

# Fig3 flow
fig, ax = plt.subplots(figsize=(11, 3.8))
ax.set_xlim(0, 11)
ax.set_ylim(0, 3.2)
ax.axis("off")
ax.set_title("Fig. 3  Main Annotation Workflow", fontsize=13, pad=8)
steps = ["Upload", "Case ingest", "2D/3D browse", "Manual/AI label", "Review", "Export Dataset"]
for i, s in enumerate(steps):
    x = 0.4 + i * 1.8
    box(ax, x, 1.2, 1.5, 0.9, "#E7F0FF", s, fs=9)
    if i < len(steps) - 1:
        ax.annotate("", xy=(x + 1.7, 1.65), xytext=(x + 1.5, 1.65), arrowprops=dict(arrowstyle="->", color="#234", lw=1.4))
ax.text(5.5, 0.5, "Human–AI loop: AI draft → human refine → review → trainable data", ha="center", fontsize=9)
save(fig, "fig3_annotation_flow.png")

# Fig4 surgery
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.set_xlim(0, 11)
ax.set_ylim(0, 3)
ax.axis("off")
ax.set_title("Fig. 4  Simulated Surgery ROI — Three Hard Gates", fontsize=13, pad=8)
steps = ["Select organ", "Confirm cuboid ROI", "Cut & save result"]
colors = ["#E8F7E8", "#FFF3D6", "#FFE5E5"]
for i, (s, c) in enumerate(zip(steps, colors)):
    x = 0.8 + i * 3.3
    box(ax, x, 1.1, 2.8, 1.0, c, f"Step {i+1}\n{s}", fs=10)
    if i < 2:
        ax.annotate("", xy=(x + 3.15, 1.6), xytext=(x + 2.8, 1.6), arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
ax.text(5.5, 0.4, "Persisted fields: organ_name / display_name / color + cut_planes", ha="center", fontsize=8.5)
save(fig, "fig4_surgery_flow.png")

# Fig5 ER
fig, ax = plt.subplots(figsize=(10.5, 5.8))
ax.set_xlim(0, 10.5)
ax.set_ylim(0, 6)
ax.axis("off")
ax.set_title("Fig. 5  Core Entity Relationships (Selected)", fontsize=13, pad=10)
boxes = [
    (0.4, 4.2, "cases\ncase_id, patient_id, status"),
    (3.6, 4.2, "images\nimage_id, case_id, path"),
    (6.8, 4.2, "masks\nmask_id, image_id, label_id"),
    (0.4, 2.0, "versions\nversion_id, case_id, mask_id"),
    (3.6, 2.0, "users / tasks\nrole, assignee, deadline"),
    (6.8, 2.0, "surgery_results\nresult_id, organ_*, ROI"),
]
for x, y, t in boxes:
    box(ax, x, y, 2.8, 1.3, "#F7F7F7", t, fs=8)
for a, b in [((3.2, 4.85), (3.6, 4.85)), ((6.4, 4.85), (6.8, 4.85)), ((1.8, 4.2), (1.8, 3.3)), ((5.0, 4.2), (5.0, 3.3)), ((8.2, 4.2), (8.2, 3.3))]:
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="->", color="#555", lw=1))
ax.text(5.25, 0.6, "surgery_results stores ROI geometry plus selected organ metadata for traceability.", ha="center", fontsize=8.5)
save(fig, "fig5_er.png")

# Fig6 sequence
fig, ax = plt.subplots(figsize=(10.5, 5.5))
ax.set_xlim(0, 10.5)
ax.set_ylim(0, 5.5)
ax.axis("off")
ax.set_title("Fig. 6  Save Surgery ROI Sequence (Simplified)", fontsize=13, pad=10)
actors = ["Viewer", "app.js", "API /surgery", "surgery_service", "SQLite"]
xs = [1.0, 3.0, 5.2, 7.2, 9.2]
for x, a in zip(xs, actors):
    ax.text(x, 5.1, a, ha="center", fontsize=8, fontweight="bold")
    ax.plot([x, x], [0.4, 4.85], color="#aaa", lw=1, ls="--")
msgs = [
    (0, 1, 4.5, "getSurgerySnapshot()"),
    (1, 2, 3.8, "POST /api/surgery_results"),
    (2, 3, 3.1, "validate + resolve organ"),
    (3, 4, 2.4, "INSERT surgery_results"),
    (4, 3, 1.7, "row"),
    (3, 2, 1.2, "SaveSurgeryResultResponse"),
    (2, 1, 0.7, "toast: saved"),
]
for i, j, y, t in msgs:
    ax.annotate("", xy=(xs[j], y), xytext=(xs[i], y), arrowprops=dict(arrowstyle="->", color="#234", lw=1.2))
    ax.text((xs[i] + xs[j]) / 2, y + 0.12, t, ha="center", fontsize=7.5)
save(fig, "fig6_sequence.png")

# Fig7 modules
fig, ax = plt.subplots(figsize=(11, 6))
ax.set_xlim(0, 11)
ax.set_ylim(0, 6.2)
ax.axis("off")
ax.set_title("Fig. 7  My Module Breakdown", fontsize=13, pad=10)
mods = [
    (0.3, 4.5, "Auth & Review\nJWT / tasks / submit"),
    (3.0, 4.5, "Imaging\nupload / slice / volume"),
    (5.7, 4.5, "Mask & Version\nCRUD / compare / export"),
    (8.4, 4.5, "AI Proxy\npredict / models"),
    (0.3, 2.2, "3D Rendering\nVTK / WebGL2 / MPR"),
    (3.0, 2.2, "Gestures\nMediaPipe Hands"),
    (5.7, 2.2, "Simulated Surgery\nROI FSM / persistence"),
    (8.4, 2.2, "Workstation UI\napp.js toolchain"),
]
for x, y, t in mods:
    box(ax, x, y, 2.3, 1.4, "#EEF5FF", t, fs=9)
box(ax, 2.5, 0.3, 6.0, 1.2, "#F5F5F5", "Shared: SQLite · schema migration · API contracts · GitHub branching", fs=10)
save(fig, "fig7_modules.png")

# Fig8 review
fig, ax = plt.subplots(figsize=(11, 4.2))
ax.set_xlim(0, 11)
ax.set_ylim(0, 4)
ax.axis("off")
ax.set_title("Fig. 8  Review Workflow (Simplified)", fontsize=13, pad=8)
steps = [("Login", 0.3), ("Assign task", 2.2), ("Annotate & save", 4.3), ("Submit", 6.5), ("Approve/Reject", 8.5)]
for t, x in steps:
    box(ax, x, 1.6, 1.7, 0.9, "#E8F6E8", t, fs=9)
    if x < 8:
        ax.annotate("", xy=(x + 1.85, 2.05), xytext=(x + 1.7, 2.05), arrowprops=dict(arrowstyle="->", color="#234"))
ax.text(9.35, 1.0, "Reject → annotate", ha="center", fontsize=8, color="#a33")
ax.annotate("", xy=(5.15, 1.5), xytext=(9.2, 1.5), arrowprops=dict(arrowstyle="->", color="#a33", connectionstyle="arc3,rad=0.25"))
ax.text(5.5, 0.45, "Approve may promote a 3D mask to final and update case status", ha="center", fontsize=9)
save(fig, "fig8_review_flow.png")

# Fig9 gesture
fig, ax = plt.subplots(figsize=(10.5, 4.5))
ax.set_xlim(0, 10.5)
ax.set_ylim(0, 4.5)
ax.axis("off")
ax.set_title("Fig. 9  Gesture-to-3D Action Mapping", fontsize=13, pad=8)
pairs = [
    (0.4, 2.8, "One-hand pan/orbit", "Camera orbit update"),
    (0.4, 1.2, "Two-hand pinch", "Volume zoom"),
    (5.5, 2.8, "Fingertip pick", "Organ label focus"),
    (5.5, 1.2, "Pinch to sheath", "End cut; keep cut faces"),
]
for x, y, a, b in pairs:
    box(ax, x, y, 2.2, 0.9, "#FFF4E5", a, fs=9)
    ax.annotate("", xy=(x + 3.3, y + 0.45), xytext=(x + 2.2, y + 0.45), arrowprops=dict(arrowstyle="->", color="#234"))
    box(ax, x + 3.3, y, 2.4, 0.9, "#E8F0FF", b, fs=9)
save(fig, "fig9_gesture_map.png")

# Fig test summary
fig, ax = plt.subplots(figsize=(10, 4.2))
ax.set_xlim(0, 10)
ax.set_ylim(0, 4.2)
ax.axis("off")
ax.set_title("Fig. 10  System Test Summary (Latest Automated Run)", fontsize=13, pad=10)
rows = [
    ("Automated cases", "56"),
    ("Passed", "54"),
    ("Failed", "0"),
    ("Skipped (heavy AI/train)", "2"),
    ("Pass rate", "96.43%"),
    ("Manual UI checklist", "15/15 Pass"),
    ("Verdict", "PASS"),
]
for i, (k, v) in enumerate(rows):
    y = 3.4 - i * 0.42
    ax.text(1.2, y, k, fontsize=10)
    ax.text(7.2, y, v, fontsize=10, fontweight="bold")
save(fig, "fig10_test_summary.png")

# English placeholder
fig, ax = plt.subplots(figsize=(10, 2.2))
ax.set_xlim(0, 10)
ax.set_ylim(0, 2.2)
ax.axis("off")
ax.add_patch(
    FancyBboxPatch((0.3, 0.3), 9.4, 1.6, boxstyle="round,pad=0.04", facecolor="#FAFAFA", edgecolor="#888", linestyle="--", linewidth=1.5)
)
ax.text(5, 1.3, "[Runtime UI Screenshot Placeholder]", ha="center", fontsize=14, color="#555")
ax.text(5, 0.75, "Replace with local runtime capture (login / workstation / 3D+gesture / surgery ROI)", ha="center", fontsize=9, color="#777")
save(fig, "fig_placeholder_ui.png")

print("English figures done ->", FIG_DIR)
