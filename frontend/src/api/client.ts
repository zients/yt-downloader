import type {
  ConversionCreateRequest,
  ConversionCreateResponse,
  ConversionStatusResponse,
  TaskCreateRequest,
  TaskCreateResponse,
  TaskStatusResponse,
} from "../types";

const API_BASE = "/api";

async function requestJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;

    try {
      const payload = (await response.json()) as { detail?: unknown };

      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep the status-based fallback when the error body is not JSON.
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function createTask(url: string): Promise<TaskCreateResponse> {
  const body: TaskCreateRequest = { url };

  return requestJson<TaskCreateResponse>("/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getTask(taskId: string): Promise<TaskStatusResponse> {
  return requestJson<TaskStatusResponse>(
    `/tasks/${encodeURIComponent(taskId)}`,
  );
}

export function createConversion(
  taskId: string,
  format: ConversionCreateRequest["format"],
  quality?: ConversionCreateRequest["quality"],
): Promise<ConversionCreateResponse> {
  const body: ConversionCreateRequest = {
    format,
    quality: quality ?? null,
  };

  return requestJson<ConversionCreateResponse>(
    `/tasks/${encodeURIComponent(taskId)}/conversions`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function getConversion(
  conversionId: string,
): Promise<ConversionStatusResponse> {
  return requestJson<ConversionStatusResponse>(
    `/conversions/${encodeURIComponent(conversionId)}`,
  );
}
