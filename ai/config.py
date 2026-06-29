"""AI configuration aligned with docs/01_data_flow_file_naming_standard.md."""
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

# Version tags for labels/
VERSION_MANUAL = "v1_manual"
VERSION_AI = "v2_ai"
VERSION_FUSION = "v3_fusion"
VERSION_FINAL = "final"

# Model (Day1 decision: U-Net 2D + Dice + BCE)
MODEL_ARCH = "unet_2d"
IN_CHANNELS = 1
OUT_CHANNELS = 1
LOSS_DICE_WEIGHT = 0.5
LOSS_BCE_WEIGHT = 0.5

# Training hyperparameters (Day2+ fill)
EPOCHS = 50
BATCH_SIZE = 8
LEARNING_RATE = 1e-4
IMAGE_SIZE = (256, 256)

# Paths (read ONLY from dataset/)
RAW_DIR = DATASET_ROOT / "raw"
IMAGES_DIR = DATASET_ROOT / "images"
LABELS_DIR = DATASET_ROOT / "labels"
SPLITS_DIR = DATASET_ROOT / "splits"

# Example label path pattern:
# dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_lung_nodule.png

def mask_filename(case_id: str, image_id: str, mask_id: str, version: str, label: str, ext: str = "png") -> str:
    return f"{case_id}_{image_id}_{mask_id}_{version}_{label}.{ext}"
