import { useCallback, useEffect, useState } from "react";
import {
  createCase1Task,
  downloadUrl,
  getTask,
  getTaskFiles,
  listTasks,
  parseCase1TaskIdFromHash,
  setCase1TaskHash,
  type TaskDetail,
  type TaskListRow,
  type TaskFileItem,
} from "./api";
import { TaskActionButtons } from "./TaskActionButtons";
import { PreviewPane } from "./PreviewPane";
import { TaskFileTree } from "./TaskFileTree";
import {
  CASE1_RULE_PRESETS,
  DEFAULT_INDICATOR_JUDGMENT_RULES,
} from "./case1RulePresets";

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

const TASK_STATUS_LABELS: Record<string, string> = {
  PENDING: "排队中",
  EXTRACTING: "准备材料",
  OCR_RUNNING: "文档识别中",
  AGENT_RUNNING: "指标填报中",
  COMPLETED: "已完成",
  FAILED: "失败",
};

const OUTPUT_LABELS: Record<string, string> = {
  collection_filled: "指标表（已填）",
  template_row_catalog: "指标目录明细",
  validation_report: "填表校验报告",
  collection_fill_notes: "填报依据说明",
  elements_extracted: "业务要素明细",
};

function taskStatusLabel(code: string): string {
  return TASK_STATUS_LABELS[code] ?? code;
}

function rowLabel(r: TaskListRow): string {
  return r.source_docx_filename || r.zip_filename;
}

export function Case1App() {
  const [hashTaskId, setHashTaskId] = useState<string | null>(() =>
    parseCase1TaskIdFromHash()
  );
  const [rows, setRows] = useState<TaskListRow[]>([]);
  const [listErr, setListErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  const [docxFile, setDocxFile] = useState<File | null>(null);
  const [supplements, setSupplements] = useState<FileList | null>(null);
  const [runOcr, setRunOcr] = useState(false);
  const [indicatorRules, setIndicatorRules] = useState(
    DEFAULT_INDICATOR_JUDGMENT_RULES
  );
  const [presetToAppend, setPresetToAppend] = useState(
    CASE1_RULE_PRESETS[1]?.id ?? ""
  );
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [taskFiles, setTaskFiles] = useState<TaskFileItem[]>([]);
  const [taskFilesLoading, setTaskFilesLoading] = useState(false);

  useEffect(() => {
    const onHash = () => setHashTaskId(parseCase1TaskIdFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    setPreviewPath(null);
    setTaskFiles([]);
    setTaskFilesLoading(Boolean(hashTaskId));
  }, [hashTaskId]);

  const refreshList = useCallback(async () => {
    try {
      setListErr(null);
      setRows(await listTasks(100, "case1"));
    } catch (e: unknown) {
      setListErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    const hasActive = rows.some((r) => !TERMINAL.has(r.status));
    if (!hasActive) return undefined;
    const t = window.setInterval(() => void refreshList(), 5000);
    return () => window.clearInterval(t);
  }, [rows, refreshList]);

  const loadDetail = useCallback(async (id: string) => {
    setDetailErr(null);
    try {
      const [task, files] = await Promise.all([getTask(id), getTaskFiles(id)]);
      setDetail(task);
      setTaskFiles(files);
    } catch (e: unknown) {
      setDetailErr(e instanceof Error ? e.message : String(e));
      setDetail(null);
      setTaskFiles([]);
    } finally {
      setTaskFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hashTaskId) {
      setDetail(null);
      setTaskFiles([]);
      return undefined;
    }
    let cancelled = false;
    const tick = async () => {
      if (!cancelled) await loadDetail(hashTaskId);
    };
    void tick();
    if (detail && TERMINAL.has(detail.status)) {
      return () => {
        cancelled = true;
      };
    }
    const iv = window.setInterval(() => void tick(), 2500);
    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, [hashTaskId, loadDetail, detail?.status]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormErr(null);
    if (!docxFile) {
      setFormErr("请上传尽职调查 Word 文档（.docx）");
      return;
    }
    if (!docxFile.name.toLowerCase().endsWith(".docx")) {
      setFormErr("主文件须为 .docx 格式");
      return;
    }
    setBusy(true);
    try {
      const supp = supplements ? Array.from(supplements) : [];
      const hasPdf = supp.some((f) => f.name.toLowerCase().endsWith(".pdf"));
      const res = await createCase1Task(docxFile, supp, {
        runOcr: runOcr || hasPdf,
        indicatorJudgmentRules: indicatorRules.trim(),
      });
      setCase1TaskHash(res.id);
      setDocxFile(null);
      setSupplements(null);
      setModalOpen(false);
      await refreshList();
      await loadDetail(res.id);
    } catch (err: unknown) {
      setFormErr(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const outputs = detail?.result_summary?.outputs ?? {};
  const selectedId = hashTaskId;
  const outputEntries = Object.entries(outputs).filter(([key]) => key !== "claude_log");

  return (
    <div className="app-shell case1-shell">
      <header className="app-header">
        <div className="header-row">
          <div className="brand-block">
            <span className="brand-mark">智审</span>
            <div>
              <span className="header-eyebrow">DUE DILIGENCE WORKSPACE</span>
              <h1>债权管理尽调 · 指标填报</h1>
            </div>
          </div>
          <nav className="app-nav">
            <a href="#/tasks" className="nav-link">
              材料处理
            </a>
            <a href="#/case1" className="nav-link is-active">
              债权管理尽调
            </a>
            <a href="#/case2" className="nav-link">
              财务模板填报
            </a>
          </nav>
        </div>
        <p className="lead">
          上传尽调报告与补充材料，按统一规则自动完成指标判断、备注填报与结果校验。
        </p>
      </header>

      <div className="layout-split-three case-workspace-layout">
        <aside className="pane pane-list card">
          <div className="pane-toolbar">
            <button type="button" onClick={() => setModalOpen(true)}>
              新建项目
            </button>
            <button type="button" className="secondary" onClick={() => void refreshList()}>
              刷新列表
            </button>
          </div>
          <h2 className="pane-title">项目列表</h2>
          {listErr ? <p className="err">{listErr}</p> : null}
          <div className="table-wrap table-wrap-list">
            <table className="task-table task-table-compact case-task-table">
              <thead><tr><th className="td-index">序号</th><th>尽调报告</th><th>处理状态</th><th>当前进展</th></tr></thead>
              <tbody>
                {rows.map((r, index) => (
                  <tr key={r.id} className={selectedId === r.id ? "row-active" : undefined}
                    onClick={() => { setCase1TaskHash(r.id); setPreviewPath(null); }} tabIndex={0}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setCase1TaskHash(r.id); setPreviewPath(null); } }}>
                    <td className="td-index">{index + 1}</td>
                    <td className="mono td-filename" title={rowLabel(r)}>{rowLabel(r)}</td>
                    <td><span className={`status-badge status-${r.status}`}>{taskStatusLabel(r.status)}</span></td>
                    <td className="muted small">{r.progress_message || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 ? <p className="muted list-empty">暂无项目，请新建项目。</p> : null}
          </div>
        </aside>

        <main className="pane pane-detail card">
          <div className="section-head"><h2 className="section-title">项目成果</h2></div>
          {!hashTaskId ? (
            <div className="detail-empty"><p>请从左侧选择项目查看处理成果。</p></div>
          ) : detailErr ? <p className="err">{detailErr}</p> : !detail ? (
            <p className="muted">加载中…</p>
          ) : (
            <div className="case-result-content">
              <section className="case-file-tree-section">
                <h3>项目文件</h3>
                <TaskFileTree files={taskFiles} selectedPath={previewPath}
                  onSelect={setPreviewPath} loading={taskFilesLoading} />
              </section>
              <p><strong>{detail.source_docx_filename || detail.zip_filename}</strong></p>
              <p><span className={`status-badge status-${detail.status}`}>{taskStatusLabel(detail.status)}</span>
                {detail.progress_message ? <span className="muted case-progress-text">{detail.progress_message}</span> : null}
              </p>
              {detail.error_message ? <pre className="err-block">{detail.error_message}</pre> : null}
              <TaskActionButtons taskId={detail.id} status={detail.status}
                onAction={async () => { await refreshList(); await loadDetail(detail.id); }}
                onDeleted={() => { setCase1TaskHash(null); void refreshList(); }} />
              {detail.indicator_judgment_rules ? (
                <details className="case1-rules-detail"><summary>本项目指标判断规则</summary>
                  <pre className="rules-preview">{detail.indicator_judgment_rules}</pre>
                </details>
              ) : null}
              {detail.status === "COMPLETED" ? (
                <div className="result-file-list">
                  {outputEntries.map(([key, rel]) => (
                    <button key={key} type="button"
                      className={`result-file-item${previewPath === rel ? " is-selected" : ""}`}
                      onClick={() => setPreviewPath(rel)}>
                      <span>{OUTPUT_LABELS[key] ?? key}</span><small>{rel}</small>
                    </button>
                  ))}
                </div>
              ) : !TERMINAL.has(detail.status) ? (
                <p className="muted case1-wait-hint">项目处理中，页面将自动刷新。</p>
              ) : null}
            </div>
          )}
        </main>

        <aside className="pane pane-preview card preview-card">
          <div className="preview-toolbar">
            <h2 className="pane-title preview-toolbar-title">文件预览</h2>
            {selectedId && previewPath ? (
              <><span className="preview-path mono small" title={previewPath}>{previewPath}</span>
                <a className="secondary preview-dl-btn" href={downloadUrl(selectedId, previewPath)} download>下载</a></>
            ) : null}
          </div>
          <div className="preview-body">
            {selectedId ? <PreviewPane taskId={selectedId} relativePath={previewPath} /> :
              <div className="preview-empty"><p>请先选择项目和成果文件。</p></div>}
          </div>
        </aside>
      </div>

      {modalOpen ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-dialog modal-dialog-wide card" role="dialog" aria-modal="true"
          >
            <div className="modal-head"><h2 className="section-title">新建债权管理尽调项目</h2>
              <button type="button" className="modal-close" disabled={busy} onClick={() => setModalOpen(false)}>×</button>
            </div>
            <form onSubmit={(e) => void onSubmit(e)} className="case1-form">
            <label className="field">
              <span>尽职调查报告（必填）</span>
              <input
                type="file"
                accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(e) => setDocxFile(e.target.files?.[0] ?? null)}
                disabled={busy}
              />
            </label>
            <label className="field">
              <span>补充材料（可选，可多选）</span>
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.pptx,.ppt,.xlsx,.xlsm,.txt,.md"
                onChange={(e) => setSupplements(e.target.files)}
                disabled={busy}
              />
              <span className="muted small">
                含扫描件时将自动启用文字识别；PPT/可研仅作背景补充。
              </span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={runOcr}
                onChange={(e) => setRunOcr(e.target.checked)}
                disabled={busy}
              />
              执行扫描件文字识别（补充扫描件时建议开启）
            </label>
            <label className="field">
              <span>指标判断规则（选填，系统将优先遵循）</span>
              <textarea
                className="case1-rules-textarea"
                rows={10}
                value={indicatorRules}
                onChange={(e) => setIndicatorRules(e.target.value)}
                disabled={busy}
                placeholder="填写本项目特有的指标判断口径…"
              />
              <div className="case1-rules-preset-row">
                <select
                  value={presetToAppend}
                  onChange={(e) => setPresetToAppend(e.target.value)}
                  disabled={busy}
                >
                  {CASE1_RULE_PRESETS.filter((p) => p.id !== "general").map(
                    (p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    )
                  )}
                </select>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy || !presetToAppend}
                  onClick={() => {
                    const preset = CASE1_RULE_PRESETS.find(
                      (p) => p.id === presetToAppend
                    );
                    if (!preset) return;
                    setIndicatorRules((prev) =>
                      prev.trim()
                        ? `${prev.trim()}\n\n${preset.content}`
                        : preset.content
                    );
                  }}
                >
                  追加预置
                </button>
              </div>
              <span className="muted small">
                默认已载入「通用总则」；可编辑或追加当地政策、增信、去化等预置。
              </span>
            </label>
            {formErr ? <p className="err">{formErr}</p> : null}
            <button type="submit" disabled={busy}>
              {busy ? "提交中…" : "提交并开始填报"}
            </button>
          </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
