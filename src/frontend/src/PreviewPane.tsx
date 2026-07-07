import { useEffect, useMemo, useState } from "react";
import {
  downloadUrl,
  previewUrl,
  type DocxPreview,
  type PptxPreview,
  type SpreadsheetPreview,
} from "./api";

const IMAGE_EXT = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".svg",
  ".bmp",
]);
const TEXT_EXT = new Set([
  ".md",
  ".txt",
  ".json",
  ".csv",
  ".xml",
  ".log",
  ".yaml",
  ".yml",
  ".htm",
  ".html",
  ".css",
  ".js",
  ".ts",
]);

function previewKind(
  path: string
): "pdf" | "image" | "text" | "spreadsheet" | "docx" | "pptx" | "unknown" {
  const i = path.lastIndexOf(".");
  if (i < 0) return "unknown";
  const ext = path.slice(i).toLowerCase();
  if (ext === ".pdf") return "pdf";
  if (ext === ".xlsx" || ext === ".xlsm") return "spreadsheet";
  if (ext === ".docx") return "docx";
  if (ext === ".pptx") return "pptx";
  if (IMAGE_EXT.has(ext)) return "image";
  if (TEXT_EXT.has(ext)) return "text";
  return "unknown";
}

export function PreviewPane({
  taskId,
  relativePath,
}: {
  taskId: string;
  relativePath: string | null;
}) {
  const kind = relativePath ? previewKind(relativePath) : null;
  const url = useMemo(
    () =>
      relativePath ? previewUrl(taskId, relativePath) : "",
    [taskId, relativePath]
  );

  const [textBody, setTextBody] = useState<string | null>(null);
  const [textTruncated, setTextTruncated] = useState(false);
  const [textLoading, setTextLoading] = useState(false);
  const [textErr, setTextErr] = useState<string | null>(null);
  const [sheetDoc, setSheetDoc] = useState<SpreadsheetPreview | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetErr, setSheetErr] = useState<string | null>(null);
  const [sheetFullscreen, setSheetFullscreen] = useState(false);
  const [officeDoc, setOfficeDoc] = useState<DocxPreview | PptxPreview | null>(null);
  const [officeLoading, setOfficeLoading] = useState(false);
  const [officeErr, setOfficeErr] = useState<string | null>(null);
  const [officeFullscreen, setOfficeFullscreen] = useState(false);
  const [activeSlide, setActiveSlide] = useState(0);

  useEffect(() => {
    setTextBody(null);
    setTextTruncated(false);
    setTextErr(null);
    if (!relativePath || kind !== "text") return undefined;

    let cancelled = false;
    setTextLoading(true);
    void fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || res.statusText);
        }
        const trunc = res.headers.get("X-Preview-Truncated") === "true";
        return res.text().then((body) => ({ body, trunc }));
      })
      .then(({ body, trunc }) => {
        if (!cancelled) {
          setTextBody(body);
          setTextTruncated(trunc);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setTextErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setTextLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [relativePath, kind, url]);

  useEffect(() => {
    setOfficeDoc(null);
    setOfficeErr(null);
    setActiveSlide(0);
    if (!relativePath || (kind !== "docx" && kind !== "pptx")) return undefined;
    let cancelled = false;
    setOfficeLoading(true);
    void fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail || res.statusText);
        }
        return res.json() as Promise<DocxPreview | PptxPreview>;
      })
      .then((doc) => {
        if (!cancelled) setOfficeDoc(doc);
      })
      .catch((error: unknown) => {
        if (!cancelled)
          setOfficeErr(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setOfficeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [relativePath, kind, url]);

  useEffect(() => {
    if (!sheetFullscreen && !officeFullscreen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSheetFullscreen(false);
        setOfficeFullscreen(false);
      }
    };
    document.body.classList.add("spreadsheet-fullscreen-open");
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.classList.remove("spreadsheet-fullscreen-open");
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [sheetFullscreen, officeFullscreen]);

  useEffect(() => {
    setSheetDoc(null);
    setActiveSheet(0);
    setSheetErr(null);
    if (!relativePath || kind !== "spreadsheet") return undefined;

    let cancelled = false;
    setSheetLoading(true);
    void fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail || res.statusText);
        }
        return res.json() as Promise<SpreadsheetPreview>;
      })
      .then((doc) => {
        if (!cancelled) setSheetDoc(doc);
      })
      .catch((error: unknown) => {
        if (!cancelled)
          setSheetErr(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setSheetLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [relativePath, kind, url]);

  if (!relativePath) {
    return (
      <div className="preview-pane-root">
        <div className="preview-empty">
          <p>在分类文件列表中点击文件，将在此处预览。</p>
          <p className="muted small">
            支持 PDF、常见图片与文本类文件；其他格式请使用下载。
          </p>
        </div>
      </div>
    );
  }

  const dl = downloadUrl(taskId, relativePath);

  if (kind === "pdf") {
    return (
      <div className="preview-pane-root">
        <iframe
          className="preview-frame preview-frame-pdf"
          title={`预览 ${relativePath}`}
          src={url}
        />
      </div>
    );
  }

  if (kind === "image") {
    return (
      <div className="preview-pane-root">
        <div className="preview-image-wrap">
          <img
            className="preview-image"
            src={url}
            alt={relativePath}
          />
        </div>
      </div>
    );
  }

  if (kind === "text") {
    if (textLoading)
      return (
        <div className="preview-pane-root">
          <p className="muted">加载文本…</p>
        </div>
      );
    if (textErr)
      return (
        <div className="preview-pane-root">
          <div className="preview-fallback">
            <p className="err">{textErr}</p>
            <a href={dl} download>
              下载文件
            </a>
          </div>
        </div>
      );
    return (
      <div className="preview-pane-root">
        <div className="preview-text-wrap">
          {textTruncated ? (
            <p className="preview-trunc-hint muted small">内容已截断显示</p>
          ) : null}
          <pre className="preview-text mono">{textBody ?? ""}</pre>
        </div>
      </div>
    );
  }

  if (kind === "spreadsheet") {
    if (sheetLoading) {
      return <div className="preview-pane-root"><p className="muted">正在解析 Excel…</p></div>;
    }
    if (sheetErr) {
      return (
        <div className="preview-pane-root">
          <div className="preview-fallback">
            <p className="err">{sheetErr}</p>
            <a href={dl} download>下载文件</a>
          </div>
        </div>
      );
    }
    const sheet = sheetDoc?.sheets[activeSheet];
    return (
      <div
        className={`preview-pane-root spreadsheet-preview${
          sheetFullscreen ? " is-fullscreen" : ""
        }`}
      >
        <div className="spreadsheet-toolbar">
          {sheetDoc && sheetDoc.sheets.length > 1 ? (
            <div className="spreadsheet-tabs" role="tablist" aria-label="工作表">
              {sheetDoc.sheets.map((item, index) => (
                <button
                  key={item.name}
                  type="button"
                  role="tab"
                  aria-selected={activeSheet === index}
                  className={activeSheet === index ? "is-active" : ""}
                  onClick={() => setActiveSheet(index)}
                >
                  {item.name}
                </button>
              ))}
            </div>
          ) : <span />}
          <button
            type="button"
            className="spreadsheet-fullscreen-btn"
            onClick={() => setSheetFullscreen((value) => !value)}
            aria-label={sheetFullscreen ? "退出全屏预览" : "全屏预览"}
          >
            {sheetFullscreen ? "退出全屏" : "全屏预览"}
          </button>
        </div>
        {sheet ? (
          <>
            <div className="spreadsheet-meta">
              <span>{sheet.name}</span>
              <span>{sheet.total_rows} 行 × {sheet.total_columns} 列</span>
              {sheet.truncated ? <span className="spreadsheet-limit">仅展示前 {sheetDoc?.limits.rows} 行、{sheetDoc?.limits.columns} 列</span> : null}
            </div>
            <div className="spreadsheet-table-wrap">
              <table className="spreadsheet-table">
                <tbody>
                  {sheet.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      <th className="spreadsheet-row-number">{rowIndex + 1}</th>
                      {row.map((value, columnIndex) => (
                        <td key={columnIndex} title={String(value ?? "")}>
                          {String(value ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="preview-empty"><p>工作簿中没有可预览内容。</p></div>
        )}
      </div>
    );
  }

  if (kind === "docx" || kind === "pptx") {
    if (officeLoading) {
      return <div className="preview-pane-root"><p className="muted">正在解析文档…</p></div>;
    }
    if (officeErr) {
      return (
        <div className="preview-pane-root"><div className="preview-fallback">
          <p className="err">{officeErr}</p><a href={dl} download>下载文件</a>
        </div></div>
      );
    }
    const fullscreenButton = (
      <button type="button" className="spreadsheet-fullscreen-btn"
        onClick={() => setOfficeFullscreen((value) => !value)}>
        {officeFullscreen ? "退出全屏" : "全屏预览"}
      </button>
    );
    if (kind === "docx" && officeDoc && "blocks" in officeDoc) {
      return (
        <div className={`preview-pane-root office-preview docx-preview${officeFullscreen ? " is-fullscreen" : ""}`}>
          <div className="office-preview-toolbar">
            <span>{officeDoc.paragraph_count} 个段落 · {officeDoc.table_count} 个表格</span>
            {fullscreenButton}
          </div>
          <div className="docx-page">
            {officeDoc.blocks.map((block, index) =>
              block.type === "paragraph" ? (
                <p key={index} className={`docx-paragraph ${block.style.toLowerCase().includes("heading") ? "is-heading" : ""}`}>
                  {block.text}
                </p>
              ) : (
                <div key={index} className="docx-table-wrap">
                  <table>{block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>{row.map((value, cellIndex) => (
                      <td key={cellIndex}>{String(value ?? "")}</td>
                    ))}</tr>
                  ))}</table>
                </div>
              )
            )}
          </div>
        </div>
      );
    }
    if (kind === "pptx" && officeDoc && "slides" in officeDoc) {
      const slide = officeDoc.slides[activeSlide];
      return (
        <div className={`preview-pane-root office-preview pptx-preview${officeFullscreen ? " is-fullscreen" : ""}`}>
          <div className="office-preview-toolbar">
            <span>共 {officeDoc.slide_count} 页</span>{fullscreenButton}
          </div>
          <div className="pptx-body">
            <div className="pptx-thumbnails">
              {officeDoc.slides.map((item, index) => (
                <button key={item.number} type="button"
                  className={activeSlide === index ? "is-active" : ""}
                  onClick={() => setActiveSlide(index)}>
                  <span>{item.number}</span><strong>{item.title}</strong>
                </button>
              ))}
            </div>
            {slide ? (
              <article className="pptx-slide">
                <span className="pptx-slide-number">{slide.number}</span>
                <h3>{slide.title}</h3>
                <div className="pptx-slide-items">
                  {slide.items.map((item, index) => <p key={index}>{item}</p>)}
                </div>
                {slide.notes ? <aside><strong>演讲者备注</strong><p>{slide.notes}</p></aside> : null}
              </article>
            ) : null}
          </div>
        </div>
      );
    }
  }

  return (
    <div className="preview-pane-root">
      <div className="preview-fallback">
        <p className="muted">当前类型不支持浏览器内预览，请下载后查看。</p>
        <p>
          <a href={dl} download>
            下载此文件
          </a>
        </p>
      </div>
    </div>
  );
}
