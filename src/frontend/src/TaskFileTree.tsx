import { FileTypeIcon } from "./FileTypeIcon";
import type { TaskFileItem } from "./api";

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function FileGroup({
  title,
  files,
  selectedPath,
  onSelect,
}: {
  title: string;
  files: TaskFileItem[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  if (files.length === 0) return null;
  return (
    <section className="task-file-group">
      <div className="task-file-group-title">
        <span>{title}</span><small>{files.length}</small>
      </div>
      <div className="task-file-tree-list">
        {files.map((file) => (
          <button
            key={file.relative_path}
            type="button"
            className={`task-file-tree-item${
              selectedPath === file.relative_path ? " is-selected" : ""
            }`}
            onClick={() => onSelect(file.relative_path)}
            title={file.relative_path}
          >
            <FileTypeIcon path={file.relative_path} />
            <span className="task-file-tree-main">
              <strong>{file.name}</strong>
              <small>{file.relative_path}</small>
            </span>
            <span className="task-file-size">{formatSize(file.size)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function TaskFileTree({
  files,
  selectedPath,
  onSelect,
  loading,
}: {
  files: TaskFileItem[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  loading?: boolean;
}) {
  if (loading) return <p className="muted small">正在加载项目文件…</p>;
  if (files.length === 0) return <p className="muted small">暂无可展示文件。</p>;
  return (
    <div className="task-file-tree">
      <FileGroup title="原始材料" files={files.filter((file) => file.source === "uploaded")}
        selectedPath={selectedPath} onSelect={onSelect} />
      <FileGroup title="成果文件" files={files.filter((file) => file.source === "output")}
        selectedPath={selectedPath} onSelect={onSelect} />
    </div>
  );
}
