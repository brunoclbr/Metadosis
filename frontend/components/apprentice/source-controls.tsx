"use client";

import { CameraIcon, ScreenIcon } from "@/components/apprentice/icons";
import {
  isVisualSourceActive,
  type VisualSourceView,
} from "@/components/apprentice/view-models";

type SourceControlsProps = {
  screen: VisualSourceView;
  camera: VisualSourceView;
};

/**
 * The two visual inputs, each started and stopped on its own.
 *
 * Failures are reported here rather than on the preview: a source that failed to
 * start has nothing to preview, so the message belongs beside the control that
 * produced it.
 */
export function SourceControls({ camera, screen }: SourceControlsProps) {
  return (
    <div className="source-controls">
      <div className="source-buttons">
        <SourceButton
          source={screen}
          icon={<ScreenIcon />}
          startLabel="Share screen"
          stopLabel="Stop sharing"
        />
        <SourceButton
          source={camera}
          icon={<CameraIcon />}
          startLabel="Enable camera"
          stopLabel="Stop camera"
        />
      </div>
      {screen.error && (
        <p className="form-error" role="alert">
          Screen: {screen.error}
        </p>
      )}
      {camera.error && (
        <p className="form-error" role="alert">
          Camera: {camera.error}
        </p>
      )}
    </div>
  );
}

function SourceButton({
  icon,
  source,
  startLabel,
  stopLabel,
}: {
  icon: React.ReactNode;
  source: VisualSourceView;
  startLabel: string;
  stopLabel: string;
}) {
  const isOn = isVisualSourceActive(source.status);
  const isRequesting = source.status === "requesting";

  return (
    <button
      className={`btn btn-source${isOn ? " is-on" : ""}`}
      type="button"
      onClick={isOn ? source.stop : source.start}
      disabled={isRequesting}
    >
      {icon}
      {isRequesting ? "Requesting…" : isOn ? stopLabel : startLabel}
    </button>
  );
}
