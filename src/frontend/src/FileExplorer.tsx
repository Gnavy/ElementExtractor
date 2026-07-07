import {
  downloadUrl,
  type ClassificationDoc,
  type ClassFile,
} from "./api";
import { FileTypeIcon } from "./FileTypeIcon";

function fileBasename(relativePath: string): string {
  const parts = relativePath.split("/").filter(Boolean);
  return parts.pop() ?? relativePath;
}

function sortFilesByName(files: ClassFile[]): ClassFile[] {
  return [...files].sort((a, b) =>
    fileBasename(a.relative_path).localeCompare(
      fileBasename(b.relative_path),
      "zh-CN"
    )
  );
}

function FileEntryRow({
  taskId,
  relativePath,
  notes,
  selectedPath,
  onSelectFile,
}: {
  taskId: string;
  relativePath: string;
  notes?: string;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  const name = fileBasename(relativePath);
  const sel = selectedPath === relativePath;
  return (
    <li className="explorer-li explorer-li-file">
      <div className="explorer-file-row">
        <button
          type="button"
          className={`explorer-file-btn task-file-tree-item${
            sel ? " is-selected" : ""
          }`}
          onClick={() => onSelectFile(relativePath)}
          title="预览"
        >
          <FileTypeIcon path={relativePath} />
          <span className="task-file-tree-main">
            <strong className="explorer-file-name">{name}</strong>
            <small className="explorer-file-path" title={relativePath}>
              {relativePath}
            </small>
          </span>
          <span className="explorer-preview-hint">预览</span>
        </button>
        <a
          className="explorer-dl"
          href={downloadUrl(taskId, relativePath)}
          download
          title="下载"
          onClick={(e) => e.stopPropagation()}
        >
          ⭳
        </a>
      </div>
      {notes ? <span className="explorer-note">{notes}</span> : null}
    </li>
  );
}

export function FileExplorer({
  taskId,
  doc,
  selectedPath,
  onSelectFile,
}: {
  taskId: string;
  doc: ClassificationDoc | null;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  if (!doc) return <p className="muted">暂无分类结果</p>;

  return (
    <div className="file-explorer">
      {doc.categories?.map((cat) => {
        const files = sortFilesByName(cat.files || []);
        return (
          <section key={cat.label} className="explorer-category">
            <div className="explorer-cat-bar">{cat.label}</div>
            {files.length === 0 ? (
              <p className="explorer-empty muted small">本分类下暂无文件</p>
            ) : (
              <ul className="explorer-file-list">
                {files.map((f) => (
                  <FileEntryRow
                    key={f.relative_path}
                    taskId={taskId}
                    relativePath={f.relative_path}
                    notes={f.notes}
                    selectedPath={selectedPath}
                    onSelectFile={onSelectFile}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
      {doc.unclassified && doc.unclassified.length > 0 ? (
        <section className="explorer-category">
          <div className="explorer-cat-bar">未分类</div>
          <ul className="explorer-file-list">
            {[...doc.unclassified]
              .sort((a, b) =>
                fileBasename(a.relative_path).localeCompare(
                  fileBasename(b.relative_path),
                  "zh-CN"
                )
              )
              .map((u) => (
                <FileEntryRow
                  key={u.relative_path}
                  taskId={taskId}
                  relativePath={u.relative_path}
                  notes={u.reason}
                  selectedPath={selectedPath}
                  onSelectFile={onSelectFile}
                />
              ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
