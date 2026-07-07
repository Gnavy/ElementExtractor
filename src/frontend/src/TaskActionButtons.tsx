import { useState } from "react";
import { Button } from "element-react";
import { deleteTask, rerunTask, resumeTask } from "./api";

type Props = {
  taskId: string;
  status: string;
  onAction?: () => void;
  onDeleted?: () => void;
};

export function TaskActionButtons({ taskId, status, onAction, onDeleted }: Props) {
  const [busy, setBusy] = useState<"resume" | "rerun" | "delete" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const canResume = status === "FAILED";
  const canRerun = status === "FAILED" || status === "COMPLETED";

  if (!canResume && !canRerun) {
    return null;
  }

  async function handleResume() {
    setErr(null);
    setBusy("resume");
    try {
      await resumeTask(taskId);
      onAction?.();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function handleRerun() {
    const msg =
      status === "COMPLETED"
        ? "将清空该项目已生成的成果文件，并从头重新处理。是否继续？"
        : "将清空该项目已有处理结果，并从头重新处理。是否继续？";
    if (!window.confirm(msg)) {
      return;
    }
    setErr(null);
    setBusy("rerun");
    try {
      await rerunTask(taskId);
      onAction?.();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (
      !window.confirm(
        "确认移除该项目？\n\n项目记录、上传材料和全部成果文件都会永久删除，此操作无法撤销。"
      )
    ) {
      return;
    }
    setErr(null);
    setBusy("delete");
    try {
      await deleteTask(taskId);
      onDeleted?.();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null;

  return (
    <div className="task-action-buttons">
      {canResume ? (
        <Button
          size="small"
          type="primary"
          className="btn-resume"
          disabled={disabled}
          onClick={() => void handleResume()}
          title="保留已有处理结果，继续完成后续环节"
        >
          {busy === "resume" ? "继续处理中…" : "继续处理"}
        </Button>
      ) : null}
      {canRerun ? (
        <>
          <Button
            size="small"
            type="danger"
            className="btn-rerun"
            disabled={disabled}
            onClick={() => void handleRerun()}
            title="清空已有成果，完整重新处理"
          >
            {busy === "rerun" ? "重新处理中…" : "重新生成"}
          </Button>
          <Button
            size="small"
            type="danger"
            className="btn-delete-task"
            disabled={disabled}
            onClick={() => void handleDelete()}
            title="永久删除项目记录和全部文件"
          >
            {busy === "delete" ? "移除中…" : "移除项目"}
          </Button>
        </>
      ) : null}
      {err ? <p className="err small">{err}</p> : null}
    </div>
  );
}
