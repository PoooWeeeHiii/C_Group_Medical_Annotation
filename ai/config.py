"""AI configuration aligned with docs/01_data_flow_file_naming_standard.md."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = PROJECT_ROOT / "dataset"
AI_ROOT = PROJECT_ROOT / "ai"
CHECKPOINT_DIR = AI_ROOT / "checkpoints"
RUNS_DIR = AI_ROOT / "runs"

# Naming (must match Person A platform)
CASE_ID_FMT = "Case{:04d}"
IMAGE_ID_FMT = "Image{:04d}"
MASK_ID_FMT = "Mask{:04d}"
DATASET_ID = "Dataset0001"
MODEL_ID = "Model0001"
SPLEEN_MODEL_ID = "Model0002"

# Version tags for labels/
VERSION_MANUAL = "v1_manual"
VERSION_AI = "v2_ai"
VERSION_FUSION = "v3_fusion"
VERSION_FINAL = "final"

# Model (platform U-Net: 2.5D by default)
MODEL_ARCH = "unet_2_5d"
IN_CHANNELS = 3  # context_radius=1 => z-1,z,z+1
OUT_CHANNELS = 6
LOSS_DICE_WEIGHT = 0.5
LOSS_BCE_WEIGHT = 0.5

# Training hyperparameters
EPOCHS = 20
BATCH_SIZE = 4
LEARNING_RATE = 1e-4
IMAGE_SIZE = (320, 320)
CONTEXT_RADIUS = 1
MAX_SLICES_PER_VOLUME = 64
CT_HU_MIN = -1000
CT_HU_MAX = 400
DEFAULT_LABEL = "lung_nodule"
SPLEEN_LABEL = "spleen"

# Paths (read ONLY from dataset/)
RAW_DIR = DATASET_ROOT / "raw"
IMAGES_DIR = DATASET_ROOT / "images"
LABELS_DIR = DATASET_ROOT / "labels"
SPLITS_DIR = DATASET_ROOT / "splits"

# Local spleen nnUNet weights (Person B machine: E:\lxy\hm_2_spleen)
_DEFAULT_SPLEEN_ROOT = Path(os.environ.get("SPLEEN_NNUNET_ROOT", r"E:\lxy\hm_2_spleen"))
SPLEEN_NNUNET_ROOT = _DEFAULT_SPLEEN_ROOT
SPLEEN_NNUNET_RESULTS = Path(
    os.environ.get("nnUNet_results", str(SPLEEN_NNUNET_ROOT / "nnUNet_results"))
)
SPLEEN_NNUNET_RAW = Path(os.environ.get("nnUNet_raw", str(SPLEEN_NNUNET_ROOT / "nnUNet_raw")))
SPLEEN_NNUNET_PREPROCESSED = Path(
    os.environ.get("nnUNet_preprocessed", str(SPLEEN_NNUNET_ROOT / "nnUNet_preprocessed"))
)
SPLEEN_MODEL_DIR = Path(
    os.environ.get(
        "SPLEEN_MODEL_DIR",
        str(
            SPLEEN_NNUNET_RESULTS
            / "Dataset506_Spleen"
            / "nnUNetTrainer_100epochs__nnUNetPlans__3d_fullres"
        ),
    )
)
SPLEEN_CHECKPOINT_NAME = os.environ.get("SPLEEN_CHECKPOINT_NAME", "checkpoint_best.pth")
SPLEEN_DATASET_ID = os.environ.get("SPLEEN_DATASET_ID", "506")
SPLEEN_CONFIGURATION = os.environ.get("SPLEEN_CONFIGURATION", "3d_fullres")
SPLEEN_TRAINER = os.environ.get("SPLEEN_TRAINER", "nnUNetTrainer_100epochs")
SPLEEN_FOLD = os.environ.get("SPLEEN_FOLD", "0")
SPLEEN_NNUNET_PYTHON = os.environ.get(
    "SPLEEN_NNUNET_PYTHON",
    r"D:\anaconda\python.exe",
)

# TotalSegmentator inference (official package; weights download on first run)
_DEFAULT_TOTALSEG_ROOT = Path(os.environ.get("TOTALSEG_ROOT", r"E:\lxy\hm_2_totalseg"))
TOTALSEG_ROOT = _DEFAULT_TOTALSEG_ROOT
TOTALSEG_PYTHON = os.environ.get(
    "TOTALSEG_PYTHON",
    r"D:\anaconda\python.exe",
)
TOTALSEG_DEVICE = os.environ.get("TOTALSEG_DEVICE", "auto")
TOTALSEG_FAST = os.environ.get("TOTALSEG_FAST", "")  # empty = auto (fast on CPU)
TOTALSEG_TIMEOUT_SECONDS = int(os.environ.get("TOTALSEG_TIMEOUT_SECONDS", "1800"))

# Example label path pattern:
# dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_spleen.nii.gz


def mask_filename(
    case_id: str,
    image_id: str,
    mask_id: str,
    version: str,
    label: str,
    ext: str = "nii.gz",
) -> str:
    return f"{case_id}_{image_id}_{mask_id}_{version}_{label}.{ext}"
