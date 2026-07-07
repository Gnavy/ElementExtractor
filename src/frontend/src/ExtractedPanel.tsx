import { useState } from "react";
import {
  downloadUrl,
  extractedExportUrl,
  type ExtractedDoc,
} from "./api";
import { ExtractFieldValue } from "./ExtractFieldValue";

export function ExtractedPanel({
  taskId,
  doc,
  onPreviewFile,
}: {
  taskId: string;
  doc: ExtractedDoc | null;
  onPreviewFile?: (relativePath: string) => void;
}) {
  const [mode, setMode] = useState<"detailed" | "compact">("detailed");

  if (!doc || !doc.fields || Object.keys(doc.fields).length === 0) {
    return <p className="muted">暂无业务要素结果</p>;
  }

  const entries = Object.entries(doc.fields);

  return (
    <div className="extracted-panel">
      <div className="extracted-toolbar">
        <div className="extracted-mode-switch">
          <button type="button" className={mode === "detailed" ? "is-active" : ""}
            onClick={() => setMode("detailed")}>详细</button>
          <button type="button" className={mode === "compact" ? "is-active" : ""}
            onClick={() => setMode("compact")}>简明</button>
        </div>
        <div className="extracted-export-actions">
          <a href={extractedExportUrl(taskId, "xlsx")} download>下载要素明细表</a>
          <a href={extractedExportUrl(taskId, "json")} download>下载结构化明细</a>
        </div>
      </div>
      {mode === "compact" ? (
        <div className="compact-extract-table-wrap">
          <table className="compact-extract-table">
            <thead><tr><th>名称</th><th>值</th></tr></thead>
            <tbody>
              {entries.map(([name, fv]) => (
                <tr key={name}>
                  <th>{name}</th>
                  <td>
                    {fv.value === null || fv.value === undefined
                      ? "—"
                      : typeof fv.value === "object"
                        ? JSON.stringify(fv.value, null, 2)
                        : String(fv.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : entries.map(([name, fv]) => (
        <article key={name} className="extract-card">
          <h4 className="extract-field-name">{name}</h4>
          <ExtractFieldValue
            taskId={taskId}
            value={fv.value}
            onPreviewFile={onPreviewFile}
          />
          {fv.confidence ? (
            <p className="extract-meta">
              置信度：<span className="badge">{fv.confidence}</span>
            </p>
          ) : null}
          {fv.source_files && fv.source_files.length > 0 ? (
            <div className="extract-sources">
              <span className="label">来源文件：</span>
              <ul className="extract-file-links">
                {fv.source_files.map((p) => (
                  <li key={p}>
                    {onPreviewFile ? (
                      <>
                        <button
                          type="button"
                          className="linkish extract-preview-link"
                          onClick={() => onPreviewFile(p)}
                        >
                          {p}
                        </button>
                        <a
                          className="extract-dl-link small muted"
                          href={downloadUrl(taskId, p)}
                          download
                        >
                          下载
                        </a>
                      </>
                    ) : (
                      <a href={downloadUrl(taskId, p)} download>
                        {p}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {fv.evidence && fv.evidence.length > 0 ? (
            <div className="extract-evidence">
              <span className="label">引用原文：</span>
              {fv.evidence.map((ev, i) => (
                <blockquote key={i} className="evidence-block">
                  <p className="evidence-quote">{ev.quote}</p>
                  <footer className="evidence-footer">
                    {onPreviewFile ? (
                      <>
                        <button
                          type="button"
                          className="linkish extract-preview-link"
                          onClick={() => onPreviewFile(ev.file)}
                        >
                          {ev.file}
                        </button>
                        <a
                          className="extract-dl-link small muted"
                          href={downloadUrl(taskId, ev.file)}
                          download
                        >
                          下载
                        </a>
                      </>
                    ) : (
                      <a href={downloadUrl(taskId, ev.file)} download>
                        {ev.file}
                      </a>
                    )}
                    {ev.page_hint ? (
                      <span className="page-hint"> · {ev.page_hint}</span>
                    ) : null}
                  </footer>
                </blockquote>
              ))}
            </div>
          ) : null}
          {fv.notes ? <p className="extract-notes">备注：{fv.notes}</p> : null}
        </article>
      ))}
    </div>
  );
}
