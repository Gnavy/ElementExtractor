import { useCallback, useEffect, useMemo, useState } from "react";
import { ExtractedPanel } from "./ExtractedPanel";
import { FileExplorer } from "./FileExplorer";
import { PreviewPane } from "./PreviewPane";
import {
  createTask,
  classificationPackageUrl,
  downloadUrl,
  getClassificationArtifact,
  getExtractedArtifact,
  getTask,
  getTaskFiles,
  listTasks,
  parseTaskIdFromHash,
  setTaskHash,
  type ClassificationDoc,
  type ExtractedDoc,
  type TaskDetail,
  type TaskListRow,
  type TaskFileItem,
} from "./api";
import {
  defaultExtractFieldRows,
  ExtractSchemaForm,
  serializeExtractSchema,
  type ExtractFieldRow,
} from "./ExtractSchemaForm";
import { TaskActionButtons } from "./TaskActionButtons";
import { TaskProgress } from "./TaskProgress";
import { TaskFileTree } from "./TaskFileTree";

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

type ClassificationIntentTemplate = {
  id: string;
  title: string;
  reason: string;
  basis: string;
  score: number;
};

const DEFAULT_CLASSIFICATION_BASIS =
  "按目录层级与文件名关键词分类：提案/尽调/法律意见、基础资料（债务人/担保人/抵押物）、财务报表与估值底稿等。";

const CLASSIFICATION_INTENT_TEMPLATES: Omit<ClassificationIntentTemplate, "score">[] = [
  {
    id: "file-type",
    title: "按文件类型归档",
    reason: "适合材料种类较杂、尚未明确业务目录时，先按 Word、PDF、Excel、图片等类型整理。",
    basis:
      "按文件类型归档：Word/文本文档、PDF 扫描件、Excel 表格、PPT 汇报材料、图片材料、压缩包展开材料、其他格式文件。每类材料内部再结合文件名识别业务用途，例如报告、合同、报表、证明、评估、审批等。",
  },
  {
    id: "filename-keywords",
    title: "按文件名关键词归档",
    reason: "适合文件名较规范，名称中包含报告、合同、财报、评估、诉讼等业务关键词的材料。",
    basis:
      "按文件名关键词归档：包含“报告/尽调/可研”的归为报告类，包含“合同/协议/借款/担保”的归为交易文件类，包含“财务/审计/报表/余额/流水”的归为财务资料类，包含“评估/估值/测算”的归为评估测算类，包含“诉讼/执行/仲裁/查封”的归为法律程序类，包含“营业执照/身份证明/章程/资质”的归为主体基础资料类，无法判断的归为其他待复核材料。",
  },
  {
    id: "folder-structure",
    title: "按目录结构归档",
    reason: "适合上传了压缩包或原始材料已按文件夹整理的项目。",
    basis:
      "优先沿用上传材料的目录层级进行归档：保留压缩包内一级/二级目录作为业务分类依据；若目录名包含主体、财务、合同、法律、抵押物、评估、审批、其他等关键词，则按对应业务类别归档；目录无法表达业务含义时，再结合文件名和正文标题补充判断。",
  },
  {
    id: "due-diligence",
    title: "尽调材料审查",
    reason: "适合包含尽调报告、提案、合同、担保、抵押、法律意见等文件的项目。",
    basis:
      "按尽调业务目录归档：项目提案/审批材料、尽调报告、交易合同与债权文件、债务人/担保人基础资料、担保与抵押物资料、法律意见与诉讼执行资料、评估与估值资料、财务报表与经营资料、其他补充材料。优先结合文件名、目录层级和正文标题判断类别。",
  },
  {
    id: "financial-reporting",
    title: "财务报表填报",
    reason: "适合包含审计报告、资产负债表、利润表、现金流量表、Excel 模板等文件的项目。",
    basis:
      "按财务填报口径归档：审计报告、资产负债表、利润表、现金流量表、附注与明细账、财务测算/估值底稿、填报模板、口径说明与校验资料、其他财务补充材料。优先识别年份、报告期、报表类型和模板文件。",
  },
  {
    id: "legal-assets",
    title: "法律与资产核验",
    reason: "适合包含合同、诉讼执行、抵押物、评估报告、权属证明等文件的项目。",
    basis:
      "按法律与资产核验目录归档：合同与协议、债权债务凭证、诉讼/仲裁/执行材料、抵质押与担保资料、权属证明、资产评估报告、查封处置材料、主体资质文件、其他法律补充材料。优先识别法律程序、资产类型、担保关系和权属文件。",
  },
  {
    id: "project-investment",
    title: "项目投资评审",
    reason: "适合包含可研、项目测算、政策、规划、估值、投资方案等文件的项目。",
    basis:
      "按项目投资评审目录归档：项目可研/商业计划、投资方案与测算模型、政策与规划依据、市场与竞品资料、建设/运营资料、估值与评估底稿、风险与合规材料、审批汇报材料、其他项目补充材料。优先识别项目阶段、测算口径和政策来源。",
  },
];

function keywordScore(text: string, keywords: string[]): number {
  return keywords.reduce((score, keyword) => score + (text.includes(keyword) ? 1 : 0), 0);
}

function classificationIntentTemplates(files: File[]): ClassificationIntentTemplate[] {
  const names = files.map((file) => file.name.toLowerCase()).join(" ");
  if (!names) {
    return CLASSIFICATION_INTENT_TEMPLATES.slice(0, 3).map((template) => ({
      ...template,
      score: 0,
    }));
  }
  const weighted = CLASSIFICATION_INTENT_TEMPLATES.map((template) => {
    let score = 0;
    if (template.id === "due-diligence") {
      score += keywordScore(names, ["尽调", "调查", "提案", "债权", "担保", "抵押", "债务人", "法律意见"]) * 3;
    }
    if (template.id === "financial-reporting") {
      score += keywordScore(names, ["审计", "财报", "财务", "资产负债", "利润", "现金流", "报表", "xlsx", "xlsm"]) * 3;
    }
    if (template.id === "legal-assets") {
      score += keywordScore(names, ["合同", "协议", "诉讼", "执行", "仲裁", "查封", "权属", "评估", "抵押物"]) * 3;
    }
    if (template.id === "project-investment") {
      score += keywordScore(names, ["可研", "投资", "测算", "政策", "规划", "估值", "项目", "方案", "ppt"]) * 3;
    }
    if (template.id === "file-type") {
      score += keywordScore(names, [".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"]) * 2;
    }
    if (template.id === "filename-keywords") {
      score += keywordScore(names, ["报告", "合同", "协议", "财务", "审计", "评估", "诉讼", "证明", "模板"]) * 2;
    }
    if (template.id === "folder-structure") {
      score += keywordScore(names, [".zip", ".rar", ".7z"]) * 4;
    }
    return { ...template, score };
  });
  return weighted
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);
}

/** 与后端 TaskStatus 枚举一致 */
const TASK_STATUS_LABELS: Record<string, string> = {
  PENDING: "待处理",
  EXTRACTING: "材料解析中",
  OCR_RUNNING: "文档识别中",
  AGENT_RUNNING: "业务要素整理中",
  COMPLETED: "已完成",
  FAILED: "失败",
};

function taskStatusLabel(code: string): string {
  return TASK_STATUS_LABELS[code] ?? code;
}

export function App() {
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMountKey, setModalMountKey] = useState(0);

  const [files, setFiles] = useState<File[]>([]);
  const [collectionFile, setCollectionFile] = useState<File | null>(null);
  const [basis, setBasis] = useState(DEFAULT_CLASSIFICATION_BASIS);
  const [schemaRows, setSchemaRows] = useState<ExtractFieldRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [runOcr, setRunOcr] = useState(true);
  const [runAgent, setRunAgent] = useState(true);
  const [runCollectionFill, setRunCollectionFill] = useState(true);
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false);
  const intentTemplates = useMemo(() => classificationIntentTemplates(files), [files]);

  const openCreateModal = () => {
    setModalMountKey((k) => k + 1);
    setFormErr(null);
    setFiles([]);
    setBasis(DEFAULT_CLASSIFICATION_BASIS);
    setTemplateMenuOpen(false);
    setSchemaRows([]);
    setCollectionFile(null);
    setRunOcr(true);
    setRunAgent(true);
    setRunCollectionFill(true);
    setModalOpen(true);
  };

  const [hashTaskId, setHashTaskId] = useState<string | null>(() =>
    parseTaskIdFromHash()
  );
  const [rows, setRows] = useState<TaskListRow[]>([]);
  const [listErr, setListErr] = useState<string | null>(null);

  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [classDoc, setClassDoc] = useState<ClassificationDoc | null>(null);
  const [extractDoc, setExtractDoc] = useState<ExtractedDoc | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [taskFiles, setTaskFiles] = useState<TaskFileItem[]>([]);
  const [taskFilesLoading, setTaskFilesLoading] = useState(false);

  useEffect(() => {
    const onHash = () => setHashTaskId(parseTaskIdFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!modalOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) setModalOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modalOpen, busy]);

  const refreshList = useCallback(async () => {
    try {
      setListErr(null);
      const data = await listTasks(100, "general");
      setRows(data);
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
    const t = window.setInterval(() => {
      void refreshList();
    }, 5000);
    return () => window.clearInterval(t);
  }, [rows, refreshList]);

  const loadDetailBundle = useCallback(async (id: string) => {
    setDetailErr(null);
    try {
      const [d, files] = await Promise.all([getTask(id), getTaskFiles(id)]);
      setDetail(d);
      setTaskFiles(files);
      if (d.status === "COMPLETED") {
        const [c, e] = await Promise.all([
          getClassificationArtifact(id).catch(() => null),
          getExtractedArtifact(id).catch(() => null),
        ]);
        setClassDoc(c);
        setExtractDoc(e);
      } else {
        setClassDoc(null);
        setExtractDoc(null);
      }
    } catch (e: unknown) {
      setDetailErr(e instanceof Error ? e.message : String(e));
      setDetail(null);
      setClassDoc(null);
      setExtractDoc(null);
      setTaskFiles([]);
    } finally {
      setTaskFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    setPreviewPath(null);
    setTaskFilesLoading(Boolean(hashTaskId));
  }, [hashTaskId]);

  useEffect(() => {
    if (!hashTaskId) {
      setDetail(null);
      setClassDoc(null);
      setExtractDoc(null);
      setTaskFiles([]);
      return undefined;
    }
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      await loadDetailBundle(hashTaskId);
    };
    void tick();
    if (detail && TERMINAL.has(detail.status)) {
      return () => {
        cancelled = true;
      };
    }
    const iv = window.setInterval(() => {
      if (cancelled) return;
      void loadDetailBundle(hashTaskId);
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, [hashTaskId, loadDetailBundle, detail?.status]);

  function closeModal() {
    if (busy) return;
    setModalOpen(false);
    setFormErr(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormErr(null);
    if (files.length === 0) {
      setFormErr("请至少选择一个材料文件");
      return;
    }
    if (!schemaRows.some((r) => r.name.trim())) {
      setFormErr("请至少填写一条要素名");
      return;
    }
    if (!runOcr && !runAgent) {
      setFormErr("请至少选择「扫描件识别」或「材料分类与要素整理」之一");
      return;
    }
    const schemaText = serializeExtractSchema(schemaRows);
    setBusy(true);
    try {
      const res = await createTask(files, basis, schemaText, collectionFile, {
        runOcr,
        runAgent,
        runCollectionFill: collectionFile ? runCollectionFill : false,
      });
      setTaskHash(res.id);
      setFiles([]);
      setCollectionFile(null);
      setModalOpen(false);
      await refreshList();
      await loadDetailBundle(res.id);
    } catch (ex: unknown) {
      setFormErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy(false);
    }
  }

  const selectedId = hashTaskId;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-row">
          <div className="brand-block">
            <span className="brand-mark">智审</span>
            <div>
              <span className="header-eyebrow">INTELLIGENT REVIEW WORKSPACE</span>
              <h1>业务审查材料处理</h1>
            </div>
          </div>
          <nav className="app-nav">
            <a href="#/tasks" className="nav-link is-active">
              材料处理
            </a>
            <a href="#/case1" className="nav-link">
              债权管理尽调
            </a>
            <a href="#/case2" className="nav-link">
              财务模板填报
            </a>
          </nav>
        </div>
        <p className="lead">
          统一完成材料归档、业务要素提取与依据追溯，处理过程和成果文件全程可查看。
        </p>
      </header>

      <div className="layout-split-three">
        <aside className="pane pane-list card" aria-label="项目列表">
          <div className="pane-toolbar">
            <button type="button" onClick={openCreateModal}>
              新建项目
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => void refreshList()}
            >
              刷新列表
            </button>
          </div>
          <h2 className="pane-title">项目列表</h2>
          {listErr ? <p className="err">{listErr}</p> : null}
          <div className="table-wrap table-wrap-list">
            <table className="task-table task-table-compact">
              <thead>
                <tr>
                  <th className="td-index">序号</th>
                  <th>材料包</th>
                  <th>处理状态</th>
                  <th>提交时间</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, index) => (
                  <tr
                    key={r.id}
                    className={selectedId === r.id ? "row-active" : undefined}
                    onClick={() => setTaskHash(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setTaskHash(r.id);
                      }
                    }}
                    tabIndex={0}
                    title="点击查看详情"
                  >
                    <td className="td-index">{index + 1}</td>
                    <td className="mono td-filename" title={r.zip_filename}>
                      {r.zip_filename}
                    </td>
                    <td>
                      <span className={`status-badge status-${r.status}`}>
                        {taskStatusLabel(r.status)}
                      </span>
                    </td>
                    <td className="muted small td-time">
                      {/* 后端存的是 UTC 且不带时区后缀，补 Z 才不会被当成本地时间 */}
                      {new Date(r.created_at + "Z").toLocaleString(undefined, {
                        month: "2-digit",
                        day: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 ? (
              <p className="muted list-empty">暂无项目，请点击「新建项目」。</p>
            ) : null}
          </div>
          {rows.length > 0 ? (
            <p className="list-hint muted small">
              点击行选中任务；详情与预览在中间、右侧显示。
            </p>
          ) : null}
        </aside>

        <main className="pane pane-detail card detail-card" aria-label="任务详情">
          <div className="section-head">
            <h2 className="section-title">项目详情</h2>
            {selectedId ? (
              <button
                type="button"
                className="secondary"
                onClick={() => setTaskHash(null)}
              >
                取消选择
              </button>
            ) : null}
          </div>

          {!selectedId ? (
            <div className="detail-empty">
              <p>请从左侧选择一个项目，或点击「新建项目」提交材料包。</p>
            </div>
          ) : detailErr ? (
            <p className="err">{detailErr}</p>
          ) : detail ? (
            <div className="detail-body">
              <section className="detail-section detail-section-overview">
                <h3 className="detail-section-title">项目概览</h3>
                <div className="detail-section-content">
                  <p>
                    <strong>项目编号：</strong>
                    <span className="mono">{detail.id}</span>
                  </p>
                  <p>
                    <strong>处理状态：</strong>
                    <span className={`status-badge status-${detail.status}`}>
                      {taskStatusLabel(detail.status)}
                    </span>
                    {detail.progress_message ? (
                      <span className="muted" style={{ marginLeft: "0.5rem" }}>
                        {detail.progress_message}
                      </span>
                    ) : null}
                  </p>
                  <TaskProgress task={detail} />
                  <TaskActionButtons
                    taskId={detail.id}
                    status={detail.status}
                    onAction={() => void loadDetailBundle(detail.id)}
                    onDeleted={() => {
                      setTaskHash(null);
                      void refreshList();
                    }}
                  />
                  <details className="meta-block">
                    <summary>材料归档与要素提取要求</summary>
                    <p className="small-label">材料归档口径</p>
                    <pre className="mono pre-box">{detail.classification_basis}</pre>
                    <p className="small-label">要素提取清单</p>
                    <pre className="mono pre-box">{detail.extract_schema}</pre>
                  </details>
                  {detail.collection_template_original_filename ? (
                    <p className="extract-meta">
                      <span className="label">信息收集表模板：</span>
                      <span className="mono">{detail.collection_template_original_filename}</span>
                    </p>
                  ) : null}
                  <p className="extract-meta muted small">
                    <span className="label">本次执行步骤：</span>
                    扫描件识别 {detail.run_ocr !== false ? "是" : "否"} · 材料归档与要素提取{" "}
                    {detail.run_agent !== false ? "是" : "否"} · 信息收集表填报{" "}
                    {detail.run_collection_fill !== false ? "是" : "否"}
                  </p>
                </div>
              </section>
              <section className="detail-section detail-files-section">
                <h3 className="detail-section-title">项目文件</h3>
                <div className="detail-section-content">
                  <TaskFileTree files={taskFiles} selectedPath={previewPath}
                    onSelect={setPreviewPath} loading={taskFilesLoading} />
                </div>
              </section>

              {detail.status === "COMPLETED" ? (
                <>
                  <section className="detail-section">
                    <div className="detail-section-heading">
                      <h3 className="detail-section-title">材料分类</h3>
                      <a
                        className="classification-package-btn"
                        href={classificationPackageUrl(selectedId)}
                        download
                      >
                        下载分类材料包
                      </a>
                    </div>
                    <div className="detail-section-content">
                      <div className="explorer-panel">
                        <FileExplorer
                          taskId={selectedId}
                          doc={classDoc}
                          selectedPath={previewPath}
                          onSelectFile={setPreviewPath}
                        />
                      </div>
                    </div>
                  </section>
                  <section className="detail-section">
                    <h3 className="detail-section-title">业务要素结果</h3>
                    <div className="detail-section-content">
                      <ExtractedPanel
                        taskId={selectedId}
                        doc={extractDoc}
                        onPreviewFile={setPreviewPath}
                      />
                    </div>
                  </section>
                </>
              ) : (
                <div className="detail-section detail-section-pending">
                  <p className="muted">
                    项目处理完成后，将自动展示材料分类和业务要素结果。
                  </p>
                </div>
              )}
            </div>
          ) : (
            !detailErr && <p className="muted">加载中…</p>
          )}
        </main>

        <aside
          className="pane pane-preview card preview-card"
          aria-label="文件预览"
        >
          <div className="preview-toolbar">
            <h2 className="pane-title preview-toolbar-title">预览</h2>
            {selectedId && previewPath ? (
              <>
                <span className="preview-path mono small" title={previewPath}>
                  {previewPath}
                </span>
                <a
                  className="secondary preview-dl-btn"
                  href={downloadUrl(selectedId, previewPath)}
                  download
                >
                  下载
                </a>
              </>
            ) : null}
          </div>
          <div className="preview-body">
            {selectedId ? (
              <PreviewPane taskId={selectedId} relativePath={previewPath} />
            ) : (
              <div className="preview-empty">
                <p className="muted">请先选择项目后再预览文件。</p>
              </div>
            )}
          </div>
        </aside>
      </div>

      {modalOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
        >
          <div
            className="modal-dialog modal-dialog-wide card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
          >
            <div className="modal-head">
              <h2 id="modal-title" className="section-title">
                新建材料处理项目
              </h2>
              <button
                type="button"
                className="modal-close"
                onClick={closeModal}
                aria-label="关闭"
                disabled={busy}
              >
                ×
              </button>
            </div>
            <form onSubmit={onSubmit}>
              <div className="row-fields">
                <label htmlFor="materials">材料文件</label>
                <input
                  id="materials"
                  name="materials"
                  type="file"
                  multiple
                  key={modalMountKey}
                  onChange={(e) => {
                    setFiles(Array.from(e.target.files ?? []));
                    setTemplateMenuOpen(false);
                  }}
                />
                <p className="field-help">
                  支持上传多个文件；如上传压缩包，系统会自动解压并保留包内目录结构。
                </p>
                {files.length > 0 ? (
                  <p className="field-help">
                    已选择 {files.length} 个材料文件。
                  </p>
                ) : null}
              </div>
              <div className="row-fields">
                <label htmlFor="basis">材料归档口径</label>
                <div className="basis-textarea-wrap">
                  <textarea
                    id="basis"
                    value={basis}
                    onChange={(e) => setBasis(e.target.value)}
                  />
                  <button
                    type="button"
                    className="secondary basis-template-btn"
                    onClick={() => setTemplateMenuOpen((open) => !open)}
                    disabled={busy || intentTemplates.length === 0}
                    title="选择推荐归档模板"
                  >
                    套用推荐
                  </button>
                  {templateMenuOpen ? (
                    <div className="basis-template-menu">
                      {intentTemplates.map((template) => (
                        <button
                          key={template.id}
                          type="button"
                          className="basis-template-option"
                          onClick={() => {
                            setBasis(template.basis);
                            setTemplateMenuOpen(false);
                          }}
                        >
                          <strong>{template.title}</strong>
                          <span>{template.reason}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                <p className="field-help">
                  描述材料的业务目录和归档规则，系统会据此识别文件所属类别。
                </p>
              </div>
              <div className="row-fields row-fields-schema">
                <div className="schema-section-head">
                  <label className="schema-section-label" id="schema-label">
                    业务要素清单
                  </label>
                  <button
                    type="button"
                    className="secondary schema-import-sample"
                    onClick={() => setSchemaRows(defaultExtractFieldRows())}
                    disabled={busy}
                  >
                    导入示例要素
                  </button>
                </div>
                <ExtractSchemaForm rows={schemaRows} onChange={setSchemaRows} />
                <p className="field-help">
                  配置需要从材料中提取的业务字段、数据类型和判断口径；至少需要填写一项。
                </p>
              </div>
              <div className="row-fields">
                <label htmlFor="collection-xlsx">信息收集表格（可选）</label>
                <input
                  id="collection-xlsx"
                  name="collection-xlsx"
                  type="file"
                  accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
                  key={`coll-${modalMountKey}`}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    setCollectionFile(f);
                    if (f) setRunCollectionFill(true);
                    else setRunCollectionFill(false);
                  }}
                />
                <p className="field-help">
                  支持 Excel 表格，上传后可基于提取结果生成已填信息收集表。
                </p>
              </div>
              <div className="row-fields task-step-options">
                <span className="task-step-label">处理内容（仅勾选项会执行）</span>
                <p className="field-help task-step-help">
                  可按材料类型和交付目标选择处理环节。
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={runOcr}
                    onChange={(e) => setRunOcr(e.target.checked)}
                    disabled={busy}
                  />
                  扫描件文字识别
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={runAgent}
                    onChange={(e) => setRunAgent(e.target.checked)}
                    disabled={busy}
                  />
                  材料归档与业务要素提取
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={collectionFile ? runCollectionFill : false}
                    onChange={(e) => setRunCollectionFill(e.target.checked)}
                    disabled={busy || !collectionFile}
                  />
                  生成已填信息收集表（需上传模板）
                </label>
              </div>
              {formErr ? <p className="err">{formErr}</p> : null}
              <div className="modal-actions">
                <button type="submit" disabled={busy}>
                  {busy ? "提交中…" : "提交项目"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={closeModal}
                  disabled={busy}
                >
                  取消
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
