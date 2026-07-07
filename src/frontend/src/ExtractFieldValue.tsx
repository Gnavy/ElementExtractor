import { downloadUrl, previewUrl } from "./api";

function looksLikeImageCropPath(p: string): boolean {
  const lower = p.toLowerCase();
  if (/\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(lower)) return true;
  if (lower.includes("outputs/image_crops/")) return true;
  return false;
}

export function ExtractFieldValue({
  taskId,
  value,
  onPreviewFile,
}: {
  taskId: string;
  value: unknown;
  onPreviewFile?: (relativePath: string) => void;
}) {
  if (value === null || value === undefined) {
    return <span className="extract-value-empty">—</span>;
  }

  if (Array.isArray(value)) {
    const strs = value.filter((v): v is string => typeof v === "string");
    if (
      strs.length > 0 &&
      strs.length === value.length &&
      strs.every(looksLikeImageCropPath)
    ) {
      return (
        <div className="extract-crops">
          {strs.map((p) => (
            <figure key={p} className="extract-crop-figure">
              <img
                className="extract-crop-img"
                src={previewUrl(taskId, p)}
                alt=""
                loading="lazy"
              />
              <figcaption className="extract-crop-caption mono">{p}</figcaption>
              <div className="extract-crop-actions">
                {onPreviewFile ? (
                  <button
                    type="button"
                    className="linkish small"
                    onClick={() => onPreviewFile(p)}
                  >
                    在预览区打开
                  </button>
                ) : null}
                <a
                  className="small muted"
                  href={downloadUrl(taskId, p)}
                  download
                >
                  下载
                </a>
              </div>
            </figure>
          ))}
        </div>
      );
    }
    return (
      <pre className="mono extract-value-pre">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  if (typeof value === "string" && looksLikeImageCropPath(value)) {
    return (
      <div className="extract-crops extract-crops-single">
        <figure className="extract-crop-figure">
          <img
            className="extract-crop-img"
            src={previewUrl(taskId, value)}
            alt=""
            loading="lazy"
          />
          <figcaption className="extract-crop-caption mono">{value}</figcaption>
          <div className="extract-crop-actions">
            {onPreviewFile ? (
              <button
                type="button"
                className="linkish small"
                onClick={() => onPreviewFile(value)}
              >
                在预览区打开
              </button>
            ) : null}
            <a
              className="small muted"
              href={downloadUrl(taskId, value)}
              download
            >
              下载
            </a>
          </div>
        </figure>
      </div>
    );
  }

  if (typeof value === "object") {
    return (
      <pre className="mono extract-value-pre">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  return <div className="extract-value-text mono">{String(value)}</div>;
}
