const BASE = "";

export type TaskDetail = {
  id: string;
  status: string;
  progress_message: string | null;
  error_message: string | null;
  classification_basis: string;
  extract_schema: string;
  zip_filename: string;
  task_kind?: string;
  source_docx_filename?: string | null;
  indicator_judgment_rules?: string | null;
  fill_logic_rules?: string | null;
  collection_template_original_filename: string | null;
  run_ocr: boolean;
  run_agent: boolean;
  run_collection_fill: boolean;
  result_summary: {
    outputs?: Record<string, string>;
  } | null;
  claude_log_tail: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskListRow = {
  id: string;
  status: string;
  zip_filename: string;
  task_kind?: string;
  source_docx_filename?: string | null;
  progress_message: string | null;
  error_message: string | null;
  created_at: string;
};

export type TaskKindFilter = "general" | "case1" | "case2";

export type ClassFile = {
  relative_path: string;
  file_type?: string;
  notes?: string;
};

export type ClassCategory = {
  label: string;
  files: ClassFile[];
};

export type ClassificationDoc = {
  task_id?: string;
  categories: ClassCategory[];
  unclassified?: { relative_path: string; reason?: string }[];
};

export type EvidenceItem = {
  file: string;
  quote: string;
  page_hint?: string;
};

export type FieldValue = {
  value: unknown;
  confidence?: string;
  source_files?: string[];
  evidence?: EvidenceItem[];
  notes?: string;
};

export type ExtractedDoc = {
  task_id?: string;
  fields: Record<string, FieldValue>;
};

export type SpreadsheetPreviewSheet = {
  name: string;
  rows: unknown[][];
  total_rows: number;
  total_columns: number;
  truncated: boolean;
};

export type SpreadsheetPreview = {
  filename: string;
  sheets: SpreadsheetPreviewSheet[];
  limits: { rows: number; columns: number };
};

export type DocxPreview = {
  filename: string;
  blocks: Array<
    | { type: "paragraph"; text: string; style: string }
    | { type: "table"; rows: unknown[][] }
  >;
  paragraph_count: number;
  table_count: number;
  truncated: boolean;
};

export type PptxPreview = {
  filename: string;
  slides: Array<{
    number: number;
    title: string;
    items: string[];
    notes: string;
  }>;
  slide_count: number;
  truncated: boolean;
};

export type TaskFileItem = {
  name: string;
  relative_path: string;
  source: "uploaded" | "output";
  size: number;
  extension: string;
};

export async function listTasks(
  limit = 100,
  taskKind?: TaskKindFilter
): Promise<TaskListRow[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (taskKind) params.set("task_kind", taskKind);
  const res = await fetch(`${BASE}/api/tasks?${params}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createCase1Task(
  docx: File,
  supplements: File[] = [],
  options?: { runOcr?: boolean; indicatorJudgmentRules?: string }
): Promise<{ id: string; status: string }> {
  const fd = new FormData();
  fd.append("due_diligence_docx", docx);
  for (const f of supplements) {
    fd.append("supplementary_files", f);
  }
  fd.append("run_ocr", options?.runOcr ? "true" : "false");
  fd.append("indicator_judgment_rules", options?.indicatorJudgmentRules ?? "");
  const res = await fetch(`${BASE}/api/case1/tasks`, { method: "POST", body: fd });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export async function createCase2Task(
  sourceFiles: File[],
  collectionTemplate: File,
  options?: { runOcr?: boolean; fillLogicRules?: string }
): Promise<{ id: string; status: string }> {
  const fd = new FormData();
  for (const f of sourceFiles) {
    fd.append("source_files", f);
  }
  fd.append("collection_template", collectionTemplate);
  fd.append("run_ocr", options?.runOcr !== false ? "true" : "false");
  fd.append("fill_logic_rules", options?.fillLogicRules ?? "");
  const res = await fetch(`${BASE}/api/case2/tasks`, { method: "POST", body: fd });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export type CreateTaskStepOptions = {
  runOcr?: boolean;
  /** 对应后端表单字段 run_agent：分类与要素抽取（智能体） */
  runAgent?: boolean;
  runCollectionFill?: boolean;
};

export async function createTask(
  files: File[],
  classificationBasis: string,
  extractSchemaJson: string,
  collectionTemplate?: File | null,
  steps?: CreateTaskStepOptions
): Promise<{ id: string; status: string }> {
  const fd = new FormData();
  for (const file of files) {
    fd.append("files", file);
  }
  fd.append("classification_basis", classificationBasis);
  fd.append("extract_schema", extractSchemaJson);
  fd.append("run_ocr", steps?.runOcr !== false ? "true" : "false");
  fd.append("run_agent", steps?.runAgent !== false ? "true" : "false");
  fd.append(
    "run_collection_fill",
    steps?.runCollectionFill !== false ? "true" : "false"
  );
  if (collectionTemplate) {
    fd.append("collection_template", collectionTemplate);
  }
  const res = await fetch(`${BASE}/api/tasks`, { method: "POST", body: fd });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export async function getTask(id: string): Promise<TaskDetail> {
  const res = await fetch(`${BASE}/api/tasks/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getTaskFiles(id: string): Promise<TaskFileItem[]> {
  const res = await fetch(`${BASE}/api/tasks/${id}/files`);
  if (!res.ok) throw new Error(await res.text());
  const data = (await res.json()) as { files?: TaskFileItem[] };
  return data.files ?? [];
}

/** 失败任务续跑（保留已有中间产物） */
export async function resumeTask(
  taskId: string
): Promise<{ id: string; status: string }> {
  const res = await fetch(`${BASE}/api/tasks/${taskId}/resume`, {
    method: "POST",
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

/** 从头重跑（清空解压目录与 outputs） */
export async function rerunTask(
  taskId: string
): Promise<{ id: string; status: string }> {
  const res = await fetch(`${BASE}/api/tasks/${taskId}/rerun`, {
    method: "POST",
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export async function deleteTask(
  taskId: string
): Promise<{ ok: boolean; id: string }> {
  const res = await fetch(`${BASE}/api/tasks/${taskId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || res.statusText);
  }
  return res.json();
}

export async function getClassificationArtifact(
  taskId: string
): Promise<ClassificationDoc | null> {
  const res = await fetch(
    `${BASE}/api/tasks/${taskId}/artifacts/classification`
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getExtractedArtifact(
  taskId: string
): Promise<ExtractedDoc | null> {
  const res = await fetch(`${BASE}/api/tasks/${taskId}/artifacts/extracted`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function downloadUrl(taskId: string, relativePath: string): string {
  const q = encodeURIComponent(relativePath);
  return `${BASE}/api/tasks/${taskId}/download?path=${q}`;
}

export function classificationPackageUrl(taskId: string): string {
  return `${BASE}/api/tasks/${taskId}/classification-package`;
}

export function extractedExportUrl(
  taskId: string,
  format: "json" | "xlsx"
): string {
  return `${BASE}/api/tasks/${taskId}/extracted-export?format=${format}`;
}

/** 在线预览（PDF/图片/text；不支持则 415） */
export function previewUrl(taskId: string, relativePath: string): string {
  const q = encodeURIComponent(relativePath);
  return `${BASE}/api/tasks/${taskId}/preview?path=${q}`;
}

/** Hash 形如 `#/tasks` 或 `#/tasks/<uuid>` */
export function parseTaskIdFromHash(): string | null {
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (!raw || raw === "tasks") return null;
  const m = raw.match(/^tasks\/([^/]+)/);
  return m ? m[1] : null;
}

export function setTaskHash(taskId: string | null): void {
  if (taskId) {
    window.location.hash = `/tasks/${taskId}`;
  } else {
    window.location.hash = `/tasks`;
  }
}

export type AppRoute = "main" | "case1" | "case2";

export function parseAppRoute(): AppRoute {
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (raw === "case1" || raw.startsWith("case1/")) return "case1";
  if (raw === "case2" || raw.startsWith("case2/")) return "case2";
  return "main";
}

/** Hash 形如 `#/case1` 或 `#/case1/tasks/<uuid>` */
export function parseCase1TaskIdFromHash(): string | null {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const m = raw.match(/^case1\/tasks\/([^/]+)/);
  return m ? m[1] : null;
}

export function setCase1TaskHash(taskId: string | null): void {
  if (taskId) {
    window.location.hash = `/case1/tasks/${taskId}`;
  } else {
    window.location.hash = `/case1`;
  }
}

/** Hash 形如 `#/case2` 或 `#/case2/tasks/<uuid>` */
export function parseCase2TaskIdFromHash(): string | null {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const m = raw.match(/^case2\/tasks\/([^/]+)/);
  return m ? m[1] : null;
}

export function setCase2TaskHash(taskId: string | null): void {
  if (taskId) {
    window.location.hash = `/case2/tasks/${taskId}`;
  } else {
    window.location.hash = `/case2`;
  }
}
