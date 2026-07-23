import { useEffect, useRef, useState, type DragEvent } from "react";

export type ExtractFieldType =
  | "string"
  | "text"
  | "number"
  | "currency"
  | "date"
  | "boolean"
  | "array"
  | "object"
  | "image";

export type ExtractFieldRow = {
  id: string;
  name: string;
  type: ExtractFieldType;
  description: string;
};

const TYPE_OPTIONS: { value: ExtractFieldType; label: string }[] = [
  { value: "string", label: "短文本" },
  { value: "text", label: "长文本" },
  { value: "number", label: "数字" },
  { value: "currency", label: "金额" },
  { value: "date", label: "日期" },
  { value: "boolean", label: "是否" },
  { value: "array", label: "列表" },
  { value: "object", label: "结构化" },
  { value: "image", label: "图片/证件（区域截图）" },
];

function newId(): string {
  // randomUUID 仅在 HTTPS 或 localhost 等安全上下文可用，HTTP IP 访问时需回退生成表单行 ID
  return (
    globalThis.crypto?.randomUUID?.() ??
    `field-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

export function defaultExtractFieldRows(): ExtractFieldRow[] {
  return [
    // —— 营业执照（原结构化 object 拆分为多字段）——
    {
      id: newId(),
      name: "营业执照-文书名称",
      type: "string",
      description:
        "营业执照或登记信息中的正式名称，如「浙江诸暨鸿睿置业有限公司营业执照」；无扫描件时可从尽调报告债务人基本信息摘录。",
    },
    {
      id: newId(),
      name: "统一社会信用代码",
      type: "string",
      description: "18 位统一社会信用代码，字母数字组合，须与执照/登记信息完全一致。",
    },
    {
      id: newId(),
      name: "法定代表人",
      type: "string",
      description: "营业执照或工商登记载明的法定代表人姓名。",
    },
    {
      id: newId(),
      name: "企业住所",
      type: "text",
      description: "登记住所完整地址（省市区街道门牌号），可多行。",
    },
    {
      id: newId(),
      name: "注册资本_万元",
      type: "number",
      description:
        "注册资本折算为万元的纯数字（如 6000）；认缴/实缴差异写在备注，勿写入本字段。",
    },
    {
      id: newId(),
      name: "公司类型",
      type: "string",
      description: "如有限责任公司、股份有限公司等，按执照原文摘录。",
    },
    {
      id: newId(),
      name: "登记机关",
      type: "string",
      description: "发证/登记机关全称，如「诸暨市市场监督管理局」。",
    },
    {
      id: newId(),
      name: "营业执照正本区域截图",
      type: "image",
      description:
        "从营业执照扫描件裁剪正本关键区域，输出相对路径如 outputs/image_crops/营业执照正本.png；无原件则留空并注明来源。",
    },
    // —— 不动产/权属证照（原结构化 object 拆分为多字段）——
    {
      id: newId(),
      name: "权属证照-文件名称",
      type: "string",
      description:
        "不动产权证、土地使用权证、他项权证或尽调中对抵押物的概括名称，如「鸿润星广场不动产登记及土地使用权相关证照」。",
    },
    {
      id: newId(),
      name: "所有权人",
      type: "string",
      description: "权证或抵押登记载明的权利人/所有权人全称。",
    },
    {
      id: newId(),
      name: "土地坐落",
      type: "string",
      description: "土地/房屋坐落位置，含街道、路口方位等，与权证一致。",
    },
    {
      id: newId(),
      name: "不动产权证编号",
      type: "string",
      description: "不动产权证书或登记证明编号，如「浙（2019）诸暨市不动产证明第0016134号」。",
    },
    {
      id: newId(),
      name: "他项权证编号",
      type: "string",
      description: "抵押权登记的他项权利证明编号；与不动产权证明合一则填同一编号。",
    },
    {
      id: newId(),
      name: "土地使用权证号",
      type: "string",
      description: "国有土地使用证号，如「诸暨国用（2013）第90101495号」。",
    },
    {
      id: newId(),
      name: "土地用途",
      type: "string",
      description: "批准用途，如商业办公用地、商业、地下车位等，按权证原文。",
    },
    {
      id: newId(),
      name: "土地使用权类型",
      type: "string",
      description: "出让、划拨等使用权取得方式。",
    },
    {
      id: newId(),
      name: "土地面积_平方米",
      type: "number",
      description:
        "土地使用权证载土地面积，单位平方米，仅填数字（如 23316）；与规划证面积冲突时以土地证为准并在备注说明。",
    },
    {
      id: newId(),
      name: "建筑面积_平方米",
      type: "number",
      description:
        "抵押或权证载明的建筑面积（平方米），纯数字；在建工程可填已建部分面积。",
    },
    {
      id: newId(),
      name: "建筑总楼层",
      type: "number",
      description: "建筑物总层数，整数，如 21。",
    },
    {
      id: newId(),
      name: "土地取得日期",
      type: "date",
      description: "土地使用权起始/取得日期，格式 YYYY-MM-DD 或「YYYY年M月D日」。",
    },
    {
      id: newId(),
      name: "土地使用权终止日期",
      type: "date",
      description: "使用权终止日期，格式同上。",
    },
    {
      id: newId(),
      name: "抵押物评估价值_万元",
      type: "currency",
      description:
        "评估报告载明的评估价值（万元），可附评估时点与报告编号于备注；无评估则留空。",
    },
    // —— 四证、预售、抵押等（展示 string/number/currency/date/boolean/array 多样性）——
    {
      id: newId(),
      name: "建设用地规划许可证编号",
      type: "string",
      description: "证号全文，如「地字第330681201300125号」。",
    },
    {
      id: newId(),
      name: "建设工程规划许可证编号",
      type: "string",
      description: "建字第…号等建设工程规划许可证编号。",
    },
    {
      id: newId(),
      name: "建设工程规划-地上建筑面积_平方米",
      type: "number",
      description: "建设工程规划许可证载地上建筑面积，平方米，纯数字（如 88595.24 可取整或保留小数）。",
    },
    {
      id: newId(),
      name: "建筑工程施工许可证编号",
      type: "string",
      description: "施工许可证编号，如「330681201410140101」。",
    },
    {
      id: newId(),
      name: "施工合同价款_万元",
      type: "currency",
      description: "施工许可证或合同中载明的合同价格，单位万元。",
    },
    {
      id: newId(),
      name: "商品房预售许可证编号",
      type: "string",
      description: "预售许可证号，如「售许字（14）第072号」。",
    },
    {
      id: newId(),
      name: "预售写字楼面积_平方米",
      type: "number",
      description: "预售证附表中写字楼（或对应业态）预售建筑面积，平方米，纯数字。",
    },
    {
      id: newId(),
      name: "建设用地规划许可证发证日期",
      type: "date",
      description: "建设用地规划许可证签发日期。",
    },
    {
      id: newId(),
      name: "最高额抵押-担保最高债权本金_万元",
      type: "currency",
      description: "最高额抵押合同第三条载明的最高债权本金余额，单位万元（如 35000 表示叁亿伍仟万）。",
    },
    {
      id: newId(),
      name: "抵押顺位是否为第一顺位",
      type: "boolean",
      description: "根据登记/尽调判断：true=第一顺位抵押，false=非第一顺位或存在在先抵押权。",
    },
    {
      id: newId(),
      name: "仅抵押在本行证明-结论摘要",
      type: "text",
      description:
        "银行出具的「仅抵押在我行」等证明之核心结论，可多句；含他行抵押说明时一并摘录。",
    },
    {
      id: newId(),
      name: "项目涉及证照及文书清单",
      type: "array",
      description:
        "本项目材料中出现的证照/合同名称列表，每项为字符串，如四证、预售证、最高额抵押合同、尽调报告等。",
    },
  ];
}

const DESC_PLACEHOLDER = "说明抽取含义与格式要求（点击编辑）";

const SCHEMA_ICON_SVG = {
  className: "schema-action-icon",
  viewBox: "0 0 24 24",
  xmlns: "http://www.w3.org/2000/svg",
  "aria-hidden": true as const,
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconPlus() {
  return (
    <svg {...SCHEMA_ICON_SVG}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg {...SCHEMA_ICON_SVG}>
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" />
      <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  );
}

function IconGrip() {
  return (
    <svg {...SCHEMA_ICON_SVG}>
      <circle cx="9" cy="6" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="6" r="1" fill="currentColor" stroke="none" />
      <circle cx="9" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="9" cy="18" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="18" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function createEmptyRow(): ExtractFieldRow {
  return {
    id: newId(),
    name: "",
    type: "string",
    description: "",
  };
}

function reorderRows(
  rows: ExtractFieldRow[],
  fromId: string,
  toId: string,
  place: "before" | "after"
): ExtractFieldRow[] {
  const fromIdx = rows.findIndex((r) => r.id === fromId);
  const toIdx = rows.findIndex((r) => r.id === toId);
  if (fromIdx < 0 || toIdx < 0 || fromId === toId) return rows;
  const next = [...rows];
  const [moved] = next.splice(fromIdx, 1);
  let insertIdx = next.findIndex((r) => r.id === toId);
  if (place === "after") insertIdx += 1;
  next.splice(insertIdx, 0, moved);
  return next;
}

function SchemaDescriptionCell({
  rowId,
  value,
  editingId,
  onStartEdit,
  onEndEdit,
  onChange,
}: {
  rowId: string;
  value: string;
  editingId: string | null;
  onStartEdit: (id: string) => void;
  onEndEdit: () => void;
  onChange: (value: string) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isEditing = editingId === rowId;

  useEffect(() => {
    if (!isEditing || !textareaRef.current) return;
    textareaRef.current.focus();
    const len = textareaRef.current.value.length;
    textareaRef.current.setSelectionRange(len, len);
  }, [isEditing]);

  if (isEditing) {
    return (
      <textarea
        ref={textareaRef}
        className="schema-input-desc schema-input-desc-edit"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onEndEdit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onEndEdit();
          }
        }}
        placeholder={DESC_PLACEHOLDER}
        rows={4}
        aria-label="要素描述"
      />
    );
  }

  return (
    <button
      type="button"
      className={`schema-desc-display${value.trim() ? "" : " is-empty"}`}
      onClick={() => onStartEdit(rowId)}
      title="点击编辑描述"
    >
      {value.trim() || DESC_PLACEHOLDER}
    </button>
  );
}

export function serializeExtractSchema(rows: ExtractFieldRow[]): string {
  const fields = rows
    .map((r) => ({
      name: r.name.trim(),
      type: r.type,
      description: r.description.trim(),
    }))
    .filter((r) => r.name.length > 0);
  return JSON.stringify({ fields }, null, 2);
}

type DropPlace = "before" | "after";

export function ExtractSchemaForm({
  rows,
  onChange,
}: {
  rows: ExtractFieldRow[];
  onChange: (rows: ExtractFieldRow[]) => void;
}) {
  const [editingDescId, setEditingDescId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{
    id: string;
    place: DropPlace;
  } | null>(null);

  function updateRow(
    id: string,
    patch: Partial<Omit<ExtractFieldRow, "id">>
  ): void {
    onChange(
      rows.map((r) => (r.id === id ? { ...r, ...patch } : r))
    );
  }

  function insertRowAt(index: number): void {
    const next = [...rows];
    next.splice(index, 0, createEmptyRow());
    onChange(next);
  }

  function insertRowAfter(rowId: string): void {
    const idx = rows.findIndex((r) => r.id === rowId);
    if (idx < 0) return;
    insertRowAt(idx + 1);
  }

  function appendRow(): void {
    onChange([...rows, createEmptyRow()]);
  }

  function removeRow(id: string): void {
    if (editingDescId === id) setEditingDescId(null);
    onChange(rows.filter((r) => r.id !== id));
  }

  function clearDragState(): void {
    setDraggingId(null);
    setDropTarget(null);
  }

  function handleDragStart(rowId: string, e: DragEvent<HTMLButtonElement>): void {
    setDraggingId(rowId);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", rowId);
  }

  function handleDragOver(rowId: string, e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    if (!draggingId || draggingId === rowId) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const place: DropPlace =
      e.clientY < rect.top + rect.height / 2 ? "before" : "after";
    setDropTarget({ id: rowId, place });
    e.dataTransfer.dropEffect = "move";
  }

  function handleDrop(rowId: string, e: DragEvent<HTMLDivElement>): void {
    e.preventDefault();
    const fromId = draggingId ?? e.dataTransfer.getData("text/plain");
    if (!fromId || fromId === rowId) {
      clearDragState();
      return;
    }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const place: DropPlace =
      e.clientY < rect.top + rect.height / 2 ? "before" : "after";
    onChange(reorderRows(rows, fromId, rowId, place));
    clearDragState();
  }

  return (
    <div className="schema-form">
      {rows.length > 0 ? (
        <div className="schema-form-grid schema-form-header" aria-hidden>
          <span className="schema-col-drag" />
          <span>要素名</span>
          <span>类型</span>
          <span>描述</span>
          <span className="schema-form-actions-head"> </span>
        </div>
      ) : null}
      <div className="schema-form-rows">
        {rows.length === 0 ? (
          <div className="schema-empty">
            <strong>暂未配置业务要素</strong>
            <span>可手动添加要素，或导入示例要素后调整。</span>
          </div>
        ) : null}
        {rows.map((row) => {
          const isDragging = draggingId === row.id;
          const dropBefore =
            dropTarget?.id === row.id && dropTarget.place === "before";
          const dropAfter =
            dropTarget?.id === row.id && dropTarget.place === "after";

          return (
            <div
              key={row.id}
              className={[
                "schema-form-row-wrap",
                isDragging ? "is-dragging" : "",
                dropBefore ? "is-drop-before" : "",
                dropAfter ? "is-drop-after" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onDragOver={(e) => handleDragOver(row.id, e)}
              onDrop={(e) => handleDrop(row.id, e)}
              onDragLeave={(e) => {
                if (
                  e.currentTarget.contains(e.relatedTarget as Node | null)
                ) {
                  return;
                }
                if (dropTarget?.id === row.id) setDropTarget(null);
              }}
            >
              <div className="schema-form-grid schema-form-row">
                <button
                  type="button"
                  className="schema-drag-handle"
                  draggable
                  onDragStart={(e) => handleDragStart(row.id, e)}
                  onDragEnd={clearDragState}
                  aria-label="拖拽调整顺序"
                  title="拖拽调整顺序"
                >
                  <IconGrip />
                </button>
                <input
                  type="text"
                  className="schema-input-name"
                  value={row.name}
                  onChange={(e) =>
                    updateRow(row.id, { name: e.target.value })
                  }
                  placeholder="要素名，如 营业执照正本"
                  autoComplete="off"
                  spellCheck={false}
                />
                <select
                  className="schema-select-type"
                  value={row.type}
                  onChange={(e) =>
                    updateRow(row.id, {
                      type: e.target.value as ExtractFieldType,
                    })
                  }
                  aria-label={`${row.name || "要素"}的类型`}
                >
                  {TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <SchemaDescriptionCell
                  rowId={row.id}
                  value={row.description}
                  editingId={editingDescId}
                  onStartEdit={setEditingDescId}
                  onEndEdit={() => setEditingDescId(null)}
                  onChange={(description) =>
                    updateRow(row.id, { description })
                  }
                />
                <div className="schema-form-actions">
                  <button
                    type="button"
                    className="secondary schema-icon-btn schema-btn-remove"
                    onClick={() => removeRow(row.id)}
                    aria-label="删除此行"
                    title="删除此行"
                  >
                    <IconTrash />
                  </button>
                </div>
              </div>
              <div className="schema-row-insert">
                <button
                  type="button"
                  className="secondary schema-icon-btn schema-btn-insert"
                  onClick={() => insertRowAfter(row.id)}
                  aria-label="在下方插入要素"
                  title="在下方插入要素"
                >
                  <IconPlus />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <div className="schema-form-footer">
        <button
          type="button"
          className="secondary schema-icon-btn schema-btn-add"
          onClick={appendRow}
          aria-label="在末尾添加要素"
          title="在末尾添加要素"
        >
          <IconPlus />
        </button>
        <p className="muted small schema-form-hint">
          悬停行尾可插入要素；拖拽左侧手柄调整顺序。点击描述可编辑。
        </p>
      </div>
    </div>
  );
}
