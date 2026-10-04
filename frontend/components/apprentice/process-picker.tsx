"use client";

import { type FormEvent, useState } from "react";

import { PlusIcon } from "@/components/apprentice/icons";
import type { Process } from "@/lib/process-api";

type ProcessPickerProps = {
  processes: readonly Process[];
  selectedProcess: Process | null;
  isLoading: boolean;
  isCreating: boolean;
  /** Locked while a session runs so the Brain cannot be told mid-call that the
   * expert switched to a different process. */
  isLocked: boolean;
  error: string | null;
  onSelect: (processId: string) => void;
  onCreate: (title: string) => Promise<void>;
};

export function ProcessPicker({
  error,
  isCreating,
  isLoading,
  isLocked,
  onCreate,
  onSelect,
  processes,
  selectedProcess,
}: ProcessPickerProps) {
  const [isNaming, setIsNaming] = useState(false);
  const [isChanging, setIsChanging] = useState(false);
  const [title, setTitle] = useState("");

  async function submitNewProcess(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed || isCreating) return;

    await onCreate(trimmed);
    setTitle("");
    setIsNaming(false);
  }

  if (isLoading) {
    return <p className="step-note">Loading processes…</p>;
  }

  if (selectedProcess && !isChanging && !isNaming) {
    return (
      <div className="topic-selection">
        <span className="topic-selection-label">Process</span>
        <strong>{selectedProcess.title}</strong>
        {selectedProcess.description && <span>{selectedProcess.description}</span>}
        <button
          className="topic-selection-change"
          type="button"
          disabled={isLocked}
          onClick={() => setIsChanging(true)}
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div className="picker">
      <div className="picker-row">
        <label className="sr-only" htmlFor="process-select">
          Choose a process
        </label>
        <select
          className="field field-select"
          id="process-select"
          value={selectedProcess?.id ?? ""}
          disabled={isLocked}
          onChange={(event) => {
            if (event.target.value) {
              onSelect(event.target.value);
              setIsChanging(false);
            }
          }}
        >
          <option value="" disabled>
            {processes.length === 0 ? "No processes yet" : "Choose a process"}
          </option>
          {processes.map((process) => (
            <option value={process.id} key={process.id}>
              {process.title}
            </option>
          ))}
        </select>
        <button
          className="btn"
          type="button"
          disabled={isLocked}
          onClick={() => {
            setIsNaming((current) => !current);
            setIsChanging(false);
          }}
        >
          {isNaming ? "Cancel" : <><PlusIcon />New process</>}
        </button>
      </div>

      {isNaming && (
        <form className="picker-row" onSubmit={submitNewProcess}>
          <label className="sr-only" htmlFor="process-title">
            New process name
          </label>
          <input
            className="field"
            id="process-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="e.g. Supplier invoice processing"
            maxLength={200}
            autoFocus
          />
          <button
            className="btn btn-primary"
            type="submit"
            disabled={isCreating || title.trim().length === 0}
          >
            {isCreating ? "Creating…" : "Create"}
          </button>
        </form>
      )}

      {isChanging && selectedProcess && (
        <button
          className="topic-selection-cancel"
          type="button"
          onClick={() => setIsChanging(false)}
        >
          Keep {selectedProcess.title}
        </button>
      )}

      {selectedProcess?.description && (
        <p className="picker-description">{selectedProcess.description}</p>
      )}

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
