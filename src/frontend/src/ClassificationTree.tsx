import { downloadUrl, type ClassificationDoc, type ClassFile } from "./api";

type DirNode = {
  dirs: Map<string, DirNode>;
  files: { name: string; relative_path: string; notes?: string }[];
};

function emptyNode(): DirNode {
  return { dirs: new Map(), files: [] };
}

function addPath(root: DirNode, file: ClassFile): void {
  const parts = file.relative_path.split("/").filter(Boolean);
  if (parts.length === 0) return;
  const leafName = parts.pop()!;
  let cur = root;
  for (const seg of parts) {
    if (!cur.dirs.has(seg)) cur.dirs.set(seg, emptyNode());
    cur = cur.dirs.get(seg)!;
  }
  cur.files.push({
    name: leafName,
    relative_path: file.relative_path,
    notes: file.notes,
  });
}

function DirTreeView({
  node,
  taskId,
  depth,
}: {
  node: DirNode;
  taskId: string;
  depth: number;
}) {
  const pad = { paddingLeft: `${Math.min(depth, 12) * 12}px` };
  const dirEntries = [...node.dirs.entries()].sort(([a], [b]) =>
    a.localeCompare(b, "zh-CN")
  );
  const files = [...node.files].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));

  return (
    <ul className="tree-list">
      {dirEntries.map(([name, child]) => (
        <li key={`dir-${name}`}>
          <details open={depth < 2}>
            <summary className="tree-folder" style={pad}>
              {name}
            </summary>
            <DirTreeView node={child} taskId={taskId} depth={depth + 1} />
          </details>
        </li>
      ))}
      {files.map((f) => (
        <li key={f.relative_path} style={pad}>
          <a
            href={downloadUrl(taskId, f.relative_path)}
            download
            className="tree-file"
          >
            {f.name}
          </a>
          {f.notes ? (
            <span className="tree-note"> — {f.notes}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function ClassificationTree({
  taskId,
  doc,
}: {
  taskId: string;
  doc: ClassificationDoc | null;
}) {
  if (!doc) return <p className="muted">暂无分类结果</p>;

  return (
    <div className="classification-tree">
      {doc.categories?.map((cat) => {
        const root = emptyNode();
        for (const f of cat.files || []) addPath(root, f);
        return (
          <section key={cat.label} className="tree-category">
            <h4 className="tree-cat-title">{cat.label}</h4>
            <DirTreeView node={root} taskId={taskId} depth={0} />
          </section>
        );
      })}
      {doc.unclassified && doc.unclassified.length > 0 ? (
        <section className="tree-category">
          <h4 className="tree-cat-title">未分类</h4>
          <ul className="tree-list flat-files">
            {doc.unclassified.map((u) => (
              <li key={u.relative_path}>
                <a
                  href={downloadUrl(taskId, u.relative_path)}
                  download
                  className="tree-file"
                >
                  {u.relative_path}
                </a>
                {u.reason ? (
                  <span className="tree-note"> — {u.reason}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
