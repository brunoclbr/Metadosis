import type { ReactNode } from "react";

/**
 * The application's icon set.
 *
 * Stroked, 1.5px, currentColor, sized by CSS. Keeping them here stops individual
 * surfaces from inventing their own glyph style or pulling in an icon package.
 */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function ScreenIcon() {
  return (
    <Icon>
      <rect x="2.5" y="4" width="19" height="12.5" rx="1" />
      <path d="M9 20h6M12 16.5V20" />
    </Icon>
  );
}

export function CameraIcon() {
  return (
    <Icon>
      <rect x="2.5" y="6" width="19" height="13" rx="1.5" />
      <circle cx="12" cy="12.5" r="3.5" />
      <path d="M7.5 6l1-2h7l1 2" />
    </Icon>
  );
}

export function WaveformIcon() {
  return (
    <Icon>
      <path d="M4 10.5v3M8 7v10M12 4.5v15M16 7v10M20 10.5v3" />
    </Icon>
  );
}

export function EyeIcon() {
  return (
    <Icon>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.75" />
    </Icon>
  );
}

export function SparkIcon() {
  return (
    <Icon>
      <path d="M12 3c.6 5.7 3.3 8.4 9 9-5.7.6-8.4 3.3-9 9-.6-5.7-3.3-8.4-9-9 5.7-.6 8.4-3.3 9-9Z" />
    </Icon>
  );
}

export function ClockIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.75" />
    </Icon>
  );
}

export function PlusIcon() {
  return (
    <Icon>
      <path d="M12 5.5v13M5.5 12h13" />
    </Icon>
  );
}

export function ArrowRightIcon() {
  return (
    <Icon>
      <path d="M4.5 12h15M13 5.5l6.5 6.5-6.5 6.5" />
    </Icon>
  );
}

export function ArrowLeftIcon() {
  return (
    <Icon>
      <path d="M19.5 12h-15M11 5.5 4.5 12 11 18.5" />
    </Icon>
  );
}

export function CheckIcon() {
  return (
    <Icon>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </Icon>
  );
}
