import type { TaskStatusResponse } from "../types";

type TaskProgressProps = {
  task: TaskStatusResponse;
};

export function TaskProgress({ task }: TaskProgressProps) {
  const title = task.title ?? "Preparing video";
  const message = task.message ?? "Processing source video";
  const progress = task.progress ?? 0;

  return (
    <section className="task-progress" aria-live="polite">
      {task.thumbnail ? (
        <img
          className="thumbnail"
          src={task.thumbnail}
          alt={task.title ?? "Video thumbnail"}
        />
      ) : null}
      <div className="progress-copy">
        <h2>{title}</h2>
        <p>{message}</p>
        <div
          className="progress-bar"
          aria-label={`Download progress ${progress}%`}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={progress}
          role="progressbar"
        >
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
      </div>
    </section>
  );
}
