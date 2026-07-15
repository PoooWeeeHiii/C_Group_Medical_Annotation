export type Role = "annotator" | "reviewer" | "admin" | "ai_service" | string;

export interface User {
  id: number;
  username: string;
  role: Role;
  create_time?: string;
}

export interface LabelItem {
  label_id: number;
  name: string;
  display_name: string;
  color: string;
  sort_order: number;
  enabled: boolean;
  create_time?: string;
  update_time?: string;
}

export interface CaseItem {
  case_id: string;
  patient_id?: string;
  modality?: string;
  image_count?: number;
  mask_count?: number;
  status?: string;
  create_time?: string;
  reject_note?: string;
}

export interface ImageItem {
  image_id: string;
  case_id?: string;
  modality?: string;
  path?: string;
  filename?: string;
  width?: number;
  height?: number;
  slice_count?: number | null;
  spacing?: number[];
  size?: number[];
}

export interface CaseDetail {
  case_id: string;
  images: ImageItem[];
  status?: string;
  patient_id?: string;
  reject_note?: string;
}

export interface VolumeMeta {
  width?: number;
  height?: number;
  slice_count?: number;
  spacing?: number[];
}

export interface TaskItem {
  task_id: string;
  case_id: string;
  assignee_id: number;
  assignee_username?: string;
  status: string;
  deadline?: string;
  note?: string;
}

export interface MaskItem {
  mask_id: string;
  image_id: string;
  case_id?: string;
  version?: string;
  label?: string;
  label_id?: number;
  label_type?: string;
  mask_format?: string;
  status?: string;
  path?: string;
  axis?: string;
  slice_index?: number;
  width?: number;
  height?: number;
  create_time?: string;
}

export interface ModelItem {
  model_id: string;
  name?: string;
  display_name?: string;
  label?: string;
  version?: string;
  backend?: string;
  status?: string;
  description?: string;
  external_ready?: boolean;
  dice?: number | null;
}

export interface TrainJob {
  job_id: string;
  status: string;
  dataset_id?: string;
  model_id?: string;
  epochs?: number | null;
  batch_size?: number | null;
  lr?: number | null;
  num_classes?: number | null;
  context_radius?: number | null;
  current_epoch?: number | null;
  train_loss?: number | null;
  val_loss?: number | null;
  val_dice?: number | null;
  logs?: string[];
  registered_model_id?: string | null;
  checkpoint?: string | null;
  error?: string | null;
  message?: string;
    metrics?: {
      best_val_dice?: number;
      model_id?: string;
      source?: string;
      organ?: string;
      label_type?: string;
      history?: Array<{ epoch: number; val_dice?: number; train_loss?: number }>;
    };
  log_tail?: string[];
}

export interface VersionItem {
  case_id: string;
  version: string;
  annotation?: string | null;
  model?: string | null;
  dataset?: string | null;
  create_time?: string | null;
}

export interface ReviewQueueItem {
  case_id: string;
  patient_id?: string;
  modality?: string;
  status?: string;
  image_count?: number;
  mask_count?: number;
  reject_note?: string | null;
  promotable_mask_id?: string | null;
  promotable_version?: string | null;
}

export interface MaskMetricsReport {
  success?: boolean;
  mask_id: string;
  ref_mask_id?: string | null;
  version?: string | null;
  label?: string | null;
  geometric?: {
    voxel_count?: number;
    volume_ml?: number;
    connected_component_count?: number;
    largest_component_ratio?: number;
    slice_range?: number[] | string;
  } | null;
  overlap?: {
    dice?: number;
    iou?: number;
    precision?: number;
    recall?: number;
    hd95_mm?: number | null;
    volume_diff_ml?: number;
  } | null;
  error_slices?: Array<{
    axis?: string;
    slice_index?: number;
    error_voxels?: number;
    pred_voxels?: number;
    ref_voxels?: number;
  }>;
}

export interface DatasetExportResult {
  success?: boolean;
  dataset_id?: string;
  output_path?: string;
  split_path?: string;
  label_map_path?: string;
  train_count?: number;
  val_count?: number;
  test_count?: number;
  message?: string;
  materialize?: boolean;
  label_set?: string;
  version?: string;
  export_dir?: string | null;
  dataset_json_path?: string | null;
  splits_final_path?: string | null;
  report?: {
    success_count?: number;
    skipped_count?: number;
    missing_masks?: Array<{
      case_id: string;
      image_id?: string | null;
      version?: string;
      reason?: string;
    }>;
    spacing_checks?: Array<{
      case_id: string;
      image_id: string;
      mask_id: string;
      status: string;
      detail?: string | null;
    }>;
  } | null;
}

export const ROLE_TEXT: Record<string, string> = {
  annotator: "标注员",
  reviewer: "审核员",
  admin: "管理员",
  ai_service: "AI服务",
};

export const STATUS_TEXT: Record<string, string> = {
  unannotated: "未标注",
  annotated: "已标注",
  pending: "待审核",
  reviewed: "已审核",
  final: "已确认",
};

export const NAV_ITEMS = [
  { path: "/", view: "dashboard", label: "数据总览", icon: "⌁" },
  { path: "/cases", view: "cases", label: "病例中心", icon: "▤" },
  { path: "/annotation", view: "annotation", label: "标注工作台", icon: "◱" },
  { path: "/train", view: "train", label: "AI训练中心", icon: "↗" },
  { path: "/versions", view: "versions", label: "版本审核", icon: "◎" },
  { path: "/quality", view: "quality", label: "质量报告", icon: "◇" },
  { path: "/export", view: "export", label: "Dataset导出", icon: "⇩" },
  { path: "/settings", view: "settings", label: "系统设置", icon: "⚙" },
] as const;

export const PAGE_TITLES: Record<string, string> = Object.fromEntries(
  NAV_ITEMS.map((item) => [item.path === "/" ? "dashboard" : item.view, item.label]),
);
