export type Process = {
  id: string;
  title: string;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export async function listProcesses(signal?: AbortSignal): Promise<Process[]> {
  const response = await fetch("/api/brain/processes", {
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok || !Array.isArray(payload)) {
    throw new Error("Processes could not be loaded.");
  }
  return payload.filter(isProcess);
}

export async function createProcess(
  title: string,
  description?: string,
  signal?: AbortSignal,
): Promise<Process> {
  const response = await fetch("/api/brain/processes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description: description ?? null }),
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok || !isProcess(payload)) {
    throw new Error(
      errorMessage(payload) ?? "The process could not be created.",
    );
  }
  return payload;
}

function isProcess(value: unknown): value is Process {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<Process>;
  return (
    typeof candidate.id === "string" &&
    candidate.id.length > 0 &&
    typeof candidate.title === "string" &&
    candidate.title.length > 0
  );
}

function errorMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const error = (payload as { error?: unknown }).error;
  return typeof error === "string" && error.length > 0 ? error : null;
}
