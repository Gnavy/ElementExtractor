import { useCallback, useEffect, useState } from "react";
import {
  createCase2Task,
  downloadUrl,
  getTask,
  getTaskFiles,
  listTasks,
  parseCase2TaskIdFromHash,
  setCase2TaskHash,
  type TaskDetail,
  type TaskListRow,
  type TaskFileItem,
} from "./api";
import { TaskActionButtons } from "./TaskActionButtons";
import { PreviewPane } from "./PreviewPane";
import { TaskFileTree } from "./TaskFileTree";
import {
  CASE2_RULE_PRESETS,
  DEFAULT_CASE2_FILL_LOGIC_RULES,
} from "./case2RulePresets";

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

const TASK_STATUS_LABELS: Record<string, string> = {
  PENDING: "排队中",
  EXTRACTING: "准备材料",
  OCR_RUNNING: "文档识别中",
  AGENT_RUNNING: "财务数据填报中",
  COMPLETED: "已完成",
  FAILED: "失败",
};

const OUTPUT_LABELS: Record<string, string> = {
  collection_filled: "已填模板",
  collection_fill_notes: "填报说明",
  case2_fill_schema: "填报口径清单",
  case2_filled_schema: "已填数据清单",
  backfill_report: "数据回填报告",
  calc_rules_report: "计算规则报告",
  template_row_catalog: "模板目录",
  validation_report: "校验报告",
};

function taskStatusLabel(code: string): string {
  return TASK_STATUS_LABELS[code] ?? code;
}

export function Case2App() {
  const [hashTaskId, setHashTaskId] = useState<string | null>(() =>
    parseCase2TaskIdFromHash()
  );
  const [rows, setRows] = useState<TaskListRow[]>([]);
  const [listErr, setListErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  const [sourceFiles, setSourceFiles] = useState<FileList | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [runOcr, setRunOcr] = useState(true);
  const [fillLogicRules, setFillLogicRules] = useState(
    DEFAULT_CASE2_FILL_LOGIC_RULES
  );
  const [presetToAppend, setPresetToAppend] = useState("balance_sheet_calc");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [taskFiles, setTaskFiles] = useState<TaskFileItem[]>([]);
  const [taskFilesLoading, setTaskFilesLoading] = useState(false);

  useEffect(() => {
    const onHash = () => setHashTaskId(parseCase2TaskIdFromHash());
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
      setRows(await listTasks(100, "case2"));
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
    const src = sourceFiles ? Array.from(sourceFiles) : [];
    if (src.length === 0) {
      setFormErr("请上传至少一个源文件");
      return;
    }
    if (!templateFile) {
      setFormErr("请上传一个模板文件（xlsx/xlsm）");
      return;
    }
    const suf = templateFile.name.toLowerCase();
    if (!(suf.endsWith(".xlsx") || suf.endsWith(".xlsm"))) {
      setFormErr("模板文件须为 .xlsx 或 .xlsm");
      return;
    }
    setBusy(true);
    try {
      const res = await createCase2Task(src, templateFile, {
        runOcr,
        fillLogicRules,
      });
      setCase2TaskHash(res.id);
      setSourceFiles(null);
      setTemplateFile(null);
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
              <span className="header-eyebrow">FINANCIAL DATA WORKSPACE</span>
              <h1>财务模板智能填报</h1>
            </div>
          </div>
          <nav className="app-nav">
            <a href="#/tasks" className="nav-link">
              材料处理
            </a>
            <a href="#/case1" className="nav-link">
              债权管理尽调
            </a>
            <a href="#/case2" className="nav-link is-active">
              财务模板填报
            </a>
          </nav>
        </div>
        <p className="lead">
          汇总多源财务材料，依据模板口径和计算规则自动填报、校验并生成标准化成果。
        </p>
      </header>

      <div className="layout-split-three case-workspace-layout">
        <aside className="pane pane-list card">
          <div className="pane-toolbar">
            <button type="button" onClick={() => setModalOpen(true)}>新建项目</button>
            <button type="button" className="secondary" onClick={() => void refreshList()}>刷新列表</button>
          </div>
          <h2 className="pane-title">项目列表</h2>
          {listErr ? <p className="err">{listErr}</p> : null}
          <div className="table-wrap table-wrap-list">
            <table className="task-table task-table-compact case-task-table">
              <thead><tr><th className="td-index">序号</th><th>填报项目</th><th>处理状态</th><th>当前进展</th></tr></thead>
              <tbody>
                {rows.map((r, index) => (
                  <tr key={r.id} className={selectedId === r.id ? "row-active" : undefined}
                    onClick={() => { setCase2TaskHash(r.id); setPreviewPath(null); }} tabIndex={0}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setCase2TaskHash(r.id); setPreviewPath(null); } }}>
                    <td className="td-index">{index + 1}</td>
                    <td className="mono td-filename" title={r.zip_filename}>{r.zip_filename}</td>
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
          <div className="section-head"><h2 className="section-title">填报成果</h2></div>
          {!hashTaskId ? <div className="detail-empty"><p>请从左侧选择项目查看填报成果。</p></div>
          : detailErr ? <p className="err">{detailErr}</p> : !detail ? <p className="muted">加载中…</p> : (
            <div className="case-result-content">
              <section className="case-file-tree-section">
                <h3>项目文件</h3>
                <TaskFileTree files={taskFiles} selectedPath={previewPath}
                  onSelect={setPreviewPath} loading={taskFilesLoading} />
              </section>
              <p><strong>{detail.zip_filename}</strong></p>
              <p><span className={`status-badge status-${detail.status}`}>{taskStatusLabel(detail.status)}</span>
                {detail.progress_message ? <span className="muted case-progress-text">{detail.progress_message}</span> : null}
              </p>
              {detail.error_message ? <pre className="err-block">{detail.error_message}</pre> : null}
              <TaskActionButtons taskId={detail.id} status={detail.status}
                onAction={async () => { await refreshList(); await loadDetail(detail.id); }}
                onDeleted={() => { setCase2TaskHash(null); void refreshList(); }} />
              {detail.fill_logic_rules ? (
                <details className="case1-rules-detail"><summary>本项目填表规则</summary>
                  <pre className="rules-preview">{detail.fill_logic_rules}</pre>
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
              ) : !TERMINAL.has(detail.status) ? <p className="muted case1-wait-hint">项目处理中，页面将自动刷新。</p> : null}
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
            <div className="modal-head"><h2 className="section-title">新建财务模板填报项目</h2>
              <button type="button" className="modal-close" disabled={busy} onClick={() => setModalOpen(false)}>×</button>
            </div>
            <form onSubmit={(e) => void onSubmit(e)} className="case1-form">
            <label className="field">
              <span>财务材料（可多选）</span>
              <input
                type="file"
                multiple
                onChange={(e) => setSourceFiles(e.target.files)}
                disabled={busy}
              />
            </label>
            <label className="field">
              <span>填报模板（单个 Excel 文件）</span>
              <input
                type="file"
                accept=".xlsx,.xlsm"
                onChange={(e) => setTemplateFile(e.target.files?.[0] ?? null)}
                disabled={busy}
              />
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={runOcr}
                onChange={(e) => setRunOcr(e.target.checked)}
                disabled={busy}
              />
              执行扫描件文字识别（建议保持开启）
            </label>
            <label className="field">
              <span>填表逻辑与计算规则（选填，系统将优先遵循）</span>
              <textarea
                className="case1-rules-textarea"
                rows={12}
                value={fillLogicRules}
                onChange={(e) => setFillLogicRules(e.target.value)}
                disabled={busy}
                placeholder="填写本项目特有的填表口径和计算规则…"
              />
              <div className="case1-rules-preset-row">
                <select
                  value={presetToAppend}
                  onChange={(e) => setPresetToAppend(e.target.value)}
                  disabled={busy}
                >
                  {CASE2_RULE_PRESETS.filter((p) => p.id !== "general").map(
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
                    const preset = CASE2_RULE_PRESETS.find(
                      (p) => p.id === presetToAppend
                    );
                    if (!preset) return;
                    setFillLogicRules((prev) =>
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
                默认已载入「通用总则」；可追加资产负债表、利润表、现金流量表等填报口径。
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
