/** 根据扩展名展示区分明显的类型图标（SVG），避免与复选框混淆 */

export type FileIconKind =
  | "pdf"
  | "image"
  | "text"
  | "spreadsheet"
  | "word"
  | "presentation"
  | "archive"
  | "unknown";

const IMG_EXT = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".svg",
  ".bmp",
]);
const TXT_EXT = new Set([
  ".md",
  ".txt",
  ".json",
  ".xml",
  ".log",
  ".yaml",
  ".yml",
  ".htm",
  ".html",
  ".css",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".py",
  ".rs",
  ".go",
]);
const WORD_EXT = new Set([".doc", ".docx"]);
const SHEET_EXT = new Set([".xls", ".xlsx", ".csv"]);
const PRES_EXT = new Set([".ppt", ".pptx"]);
const ARCH_EXT = new Set([".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"]);

export function fileIconKind(path: string): FileIconKind {
  const i = path.lastIndexOf(".");
  if (i < 0) return "unknown";
  const ext = path.slice(i).toLowerCase();
  if (ext === ".pdf") return "pdf";
  if (IMG_EXT.has(ext)) return "image";
  if (WORD_EXT.has(ext)) return "word";
  if (SHEET_EXT.has(ext)) return "spreadsheet";
  if (PRES_EXT.has(ext)) return "presentation";
  if (ARCH_EXT.has(ext)) return "archive";
  if (TXT_EXT.has(ext)) return "text";
  return "unknown";
}

const SVG_COMMON = {
  className: "explorer-type-icon",
  viewBox: "0 0 24 24",
  xmlns: "http://www.w3.org/2000/svg",
  "aria-hidden": true as const,
};

function IconPdf() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#dc2626"
        d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm5 18H5V4h8v6h6v10zm-6-7v2h6v-2h-6zm0 4v2h6v-2h-6zm0-8v2h4v-2h-4z"
      />
    </svg>
  );
}

function IconImage() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#0d9488"
        d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM5 5h14v9.17l-3.03-3.03a1 1 0 00-1.41 0l-3.09 3.09L9.03 10.1a1 1 0 00-1.41 0L5 12.72V5zm0 14l5.5-5.5L14 18l3.5-3.5 3.5 3.5H5z"
      />
    </svg>
  );
}

function IconText() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#475569"
        d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"
      />
    </svg>
  );
}

function IconSpreadsheet() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#15803d"
        d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm5 16H5v-4h14v4zm0-6H5v-4h14v4zm-9-6V3.5L18.5 9H10zM7 15h2v2H7v-2zm4 0h2v2h-2v-2zm4 0h2v2h-2v-2zM7 9h2v2H7V9zm4 0h2v2h-2V9zm4 0h2v2h-2V9z"
      />
    </svg>
  );
}

function IconWord() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#2563eb"
        d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h8v6h6v10z"
      />
    </svg>
  );
}

function IconPresentation() {
  return (
    <svg {...SVG_COMMON}>
      <rect fill="#ea580c" x="3" y="4" width="18" height="13" rx="1.5" />
      <path fill="#fff" d="M10 7.5v7l5.5-3.5L10 7.5z" />
    </svg>
  );
}

function IconArchive() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#ca8a04"
        d="M20 6h-2.18c.11-.31.18-.65.18-1a2 2 0 00-2-2c-.09 0-.17.01-.25.03L13 5V3c0-.55-.45-1-1-1s-1 .45-1 1v2L8.25 3.03C8.17 3.01 8.09 3 8 3c-1.1 0-2 .9-2 2 0 .35.07.69.18 1H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-8 9h4v2h-4v-2zm0-4h4v2h-4v-2zm-5 8h10v2H7v-2z"
      />
    </svg>
  );
}

function IconUnknown() {
  return (
    <svg {...SVG_COMMON}>
      <path
        fill="#64748b"
        d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11z"
      />
    </svg>
  );
}

export function FileTypeIcon({ path }: { path: string }) {
  switch (fileIconKind(path)) {
    case "pdf":
      return <IconPdf />;
    case "image":
      return <IconImage />;
    case "text":
      return <IconText />;
    case "spreadsheet":
      return <IconSpreadsheet />;
    case "word":
      return <IconWord />;
    case "presentation":
      return <IconPresentation />;
    case "archive":
      return <IconArchive />;
    default:
      return <IconUnknown />;
  }
}
