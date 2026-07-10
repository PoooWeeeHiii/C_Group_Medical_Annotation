-- C_Group_Medical_Annotation database schema
-- Development target: SQLite
--
-- Current application still reads/writes database/dev_*.json.
-- This file is the formal relational schema for the next migration step.
-- It keeps the planned eight core tables:
-- users, cases, images, annotations, masks, models, datasets, versions.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('annotator', 'reviewer', 'admin', 'ai_service')),
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    modality TEXT NOT NULL DEFAULT 'CT' CHECK (modality IN ('CT')),
    source_group TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL DEFAULT 'unannotated'
        CHECK (status IN ('unannotated', 'annotated', 'pending', 'reviewed', 'final')),
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS images (
    image_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT,
    file_format TEXT,
    width INTEGER NOT NULL DEFAULT 0 CHECK (width >= 0),
    height INTEGER NOT NULL DEFAULT 0 CHECK (height >= 0),
    slice_count INTEGER CHECK (slice_count IS NULL OR slice_count >= 0),

    -- 3D CT geometry. Stored as JSON text in SQLite, for example:
    -- spacing='[0.7,0.7,3.0]', origin='[0,0,0]',
    -- direction='[1,0,0,0,1,0,0,0,1]'.
    spacing TEXT,
    origin TEXT,
    direction TEXT,

    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    image_id TEXT NOT NULL,
    user_id INTEGER,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'ai', 'fusion', 'imported')),
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS masks (
    mask_id TEXT PRIMARY KEY,
    annotation_id TEXT,
    case_id TEXT NOT NULL,
    image_id TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT 'v1_manual'
        CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),
    label TEXT NOT NULL DEFAULT 'label',
    label_id INTEGER,
    mask_format TEXT NOT NULL DEFAULT 'nii.gz' CHECK (mask_format IN ('json', 'nii.gz', 'nrrd')),
    slice_index INTEGER CHECK (slice_index IS NULL OR slice_index >= 0),
    width INTEGER CHECK (width IS NULL OR width >= 0),
    height INTEGER CHECK (height IS NULL OR height >= 0),
    encoding TEXT,

    -- JSON text fields used by 3D mask export / label propagation.
    -- source_mask_ids='["Mask0001","Mask0002"]'
    -- shape='[134,512,512]'
    -- spacing/origin/direction must match the source CT image when mask_format='nii.gz'.
    source_mask_ids TEXT,
    shape TEXT,
    spacing TEXT,
    origin TEXT,
    direction TEXT,

    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (annotation_id) REFERENCES annotations(annotation_id) ON DELETE SET NULL,
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
    FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS models (
    model_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    dice REAL CHECK (dice IS NULL OR (dice >= 0.0 AND dice <= 1.0)),
    path TEXT,
    metrics_json TEXT,
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'medical_segmentation_dataset',
    version TEXT NOT NULL DEFAULT 'final'
        CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),
    train TEXT NOT NULL DEFAULT '[]',
    val TEXT NOT NULL DEFAULT '[]',
    test TEXT NOT NULL DEFAULT '[]',
    format TEXT NOT NULL DEFAULT 'nnunet',
    manifest_path TEXT,
    split_path TEXT,
    label_map_path TEXT,
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    version TEXT NOT NULL CHECK (version IN ('v1_manual', 'v2_ai', 'v3_preview', 'v3_fusion', 'final')),

    -- Keep column names aligned with the planning document and current API.
    -- In the final implementation, annotation should store annotation_id.
    -- Current dev JSON may temporarily store a mask_id for propagation outputs.
    annotation TEXT,
    model TEXT,
    dataset TEXT,

    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (case_id, version),
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
    FOREIGN KEY (model) REFERENCES models(model_id) ON DELETE SET NULL,
    FOREIGN KEY (dataset) REFERENCES datasets(dataset_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_images_case_id ON images(case_id);
CREATE INDEX IF NOT EXISTS idx_annotations_image_id ON annotations(image_id);
CREATE INDEX IF NOT EXISTS idx_annotations_user_id ON annotations(user_id);
CREATE INDEX IF NOT EXISTS idx_masks_case_id ON masks(case_id);
CREATE INDEX IF NOT EXISTS idx_masks_image_id ON masks(image_id);
CREATE INDEX IF NOT EXISTS idx_masks_annotation_id ON masks(annotation_id);
CREATE INDEX IF NOT EXISTS idx_masks_version ON masks(version);
CREATE INDEX IF NOT EXISTS idx_versions_case_id ON versions(case_id);
CREATE INDEX IF NOT EXISTS idx_versions_version ON versions(version);
