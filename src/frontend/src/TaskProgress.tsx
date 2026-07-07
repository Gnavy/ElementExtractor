import type { TaskDetail } from "./api";

type Stage = {
  key: string;
  label: string;
  description: string;
};

const STATUS_ORDER: Record<string, number> = {
  PENDING: 0,
  EXTRACTING: 1,
  OCR_RUNNING: 2,
  AGENT_RUNNING: 3,
  COMPLETED: 4,
  FAILED: -1,
};

function taskStages(task: TaskDetail): Stage[] {
  const stages: Stage[] = [
    { key: "PENDING", label: "等待处理", description: "等待系统安排" },
    { key: "EXTRACTING", label: "材料解析", description: "整理上传材料" },
  ];
  if (task.run_ocr !== false) {
    stages.push({ key: "OCR_RUNNING", label: "文档识别", description: "识别扫描材料文字" });
  }
  if (task.run_agent !== false) {
    stages.push({
      key: "AGENT_RUNNING",
      label: "业务整理",
      description: task.run_collection_fill !== false ? "归档、提取并填表" : "归档并提取要素",
    });
  }
  stages.push({ key: "COMPLETED", label: "处理完成", description: "成果已生成" });
  return stages;
}

function failureStage(task: TaskDetail): string {
  const message = `${task.progress_message ?? ""} ${task.error_message ?? ""}`.toLowerCase();
  if (message.includes("ocr")) return "OCR_RUNNING";
  if (
    message.includes("claude") ||
    message.includes("智能体") ||
    message.includes("schema") ||
    message.includes("回填") ||
    message.includes("计算规则")
  ) {
    return "AGENT_RUNNING";
  }
  if (
    message.includes("zip") ||
    message.includes("解压") ||
    message.includes("文件不存在")
  ) {
    return "EXTRACTING";
  }
  return "AGENT_RUNNING";
}

function errorAdvice(message: string | null): string {
  const text = (message ?? "").toLowerCase();
  if (text.includes("ocr")) {
    return "建议检查扫描文件是否损坏或受密码保护；修复材料后可选择重新生成，已有处理结果可尝试继续处理。";
  }
  if (text.includes("zip") || text.includes("解压") || text.includes("文件不存在")) {
    return "建议确认材料包可正常打开、文件名无异常且材料未被移动，然后从头重新处理项目。";
  }
  if (text.includes("schema")) {
    return "建议检查业务要素名称、类型与描述是否完整，调整配置后重新提交或重新生成。";
  }
  if (text.includes("模板") || text.includes("回填") || text.includes("校验")) {
    return "建议确认模板格式、表头和工作表结构未被修改；若已有成果完整，可先尝试继续处理。";
  }
  return "建议先尝试继续处理以保留已有结果；若再次失败，再从头重新生成并检查源文件与配置。";
}

export function TaskProgress({ task }: { task: TaskDetail }) {
  const stages = taskStages(task);
  const activeOrder = STATUS_ORDER[task.status] ?? 0;
  const failedAt = task.status === "FAILED" ? failureStage(task) : null;

  return (
    <div className="task-progress">
      <div className="task-progress-head">
        <div>
          <strong>处理进展</strong>
          <span>{task.progress_message || "等待处理进展更新"}</span>
        </div>
        <span className="task-progress-count">
          {task.status === "COMPLETED"
            ? "100%"
            : task.status === "FAILED"
              ? "处理失败"
              : `${Math.max(
                  8,
                  Math.round(
                    (stages.findIndex((stage) => stage.key === task.status) /
                      Math.max(stages.length - 1, 1)) *
                      100
                  )
                )}%`}
        </span>
      </div>
      <ol className="task-progress-steps">
        {stages.map((stage) => {
          const stageOrder = STATUS_ORDER[stage.key];
          const failed = failedAt === stage.key;
          const current = task.status === stage.key;
          const completed =
            task.status === "COMPLETED" ||
            (!failedAt && stageOrder < activeOrder) ||
            (failedAt !== null &&
              stages.findIndex((item) => item.key === stage.key) <
                stages.findIndex((item) => item.key === failedAt));
          return (
            <li
              key={stage.key}
              className={[
                completed ? "is-completed" : "",
                current ? "is-current" : "",
                failed ? "is-failed" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span className="task-progress-dot">{failed ? "!" : completed ? "✓" : ""}</span>
              <div>
                <strong>{stage.label}</strong>
                <span>{failed ? "此阶段处理失败" : stage.description}</span>
              </div>
            </li>
          );
        })}
      </ol>
      {task.status === "FAILED" ? (
        <div className="task-error-feedback" role="alert">
          <div className="task-error-title">项目未能完成</div>
          <pre>{task.error_message || "系统未返回具体错误信息。"}</pre>
          <div className="task-error-advice">
            <strong>处理建议</strong>
            <span>{errorAdvice(task.error_message)}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
