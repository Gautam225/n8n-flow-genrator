import React from 'react';

export type OrbitLoaderSize = 'inline' | 'xs' | 'sm' | 'md' | 'lg' | number;

export interface OrbitLoaderProps {
  /**
   * Size presets or explicit pixel dimension:
   * - 'inline': 14px (inline text / ultra compact buttons)
   * - 'xs': 16px (standard compact buttons / icons)
   * - 'sm': 20px (standard buttons / section headers)
   * - 'md': 32px (panels / dialogs / drawers)
   * - 'lg': 48px (full-page / hero generation stages)
   */
  size?: OrbitLoaderSize;
  /** Primary accent color. Defaults to var(--brand-primary, #EA580C) */
  color?: string;
  /** Optional visible status label (e.g. "Generating workflow...") */
  label?: React.ReactNode;
  /** Placement of label relative to the orbit animation. Defaults to 'right' (or 'bottom' for md/lg centered) */
  labelPosition?: 'right' | 'bottom';
  /** Centers the loader within its parent container */
  center?: boolean;
  /** Additional CSS class names */
  className?: string;
  /** Inline style overrides */
  style?: React.CSSProperties;
  /** Accessible text for screen readers (defaults to label or 'Loading...') */
  ariaLabel?: string;
}

const SIZE_MAP: Record<string, number> = {
  inline: 14,
  xs: 16,
  sm: 20,
  md: 32,
  lg: 48,
};

export const OrbitLoader: React.FC<OrbitLoaderProps> = ({
  size = 'sm',
  color = 'var(--brand-primary, #EA580C)',
  label,
  labelPosition,
  center = false,
  className = '',
  style = {},
  ariaLabel,
}) => {
  const pixelSize = typeof size === 'number' ? size : SIZE_MAP[size] ?? 20;
  const isCompact = pixelSize <= 16;
  const computedPosition = labelPosition ?? (center || pixelSize >= 32 ? 'bottom' : 'right');
  const accessibleLabel = ariaLabel || (typeof label === 'string' ? label : 'Loading...');

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={`orbit-loader-container orbit-loader-container--${computedPosition} ${center ? 'orbit-loader-container--center' : ''} ${className}`}
      style={style}
    >
      <span className="sr-only">{accessibleLabel}</span>
      <svg
        className="orbit-loader-svg"
        width={pixelSize}
        height={pixelSize}
        viewBox="0 0 40 40"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ color }}
        aria-hidden="true"
      >
        {/* Core Center Dot */}
        <circle
          cx="20"
          cy="20"
          r={isCompact ? 3.5 : 3}
          fill="currentColor"
          className="orbit-core"
        />

        {/* Outer Orbit Track */}
        <circle
          cx="20"
          cy="20"
          r="15"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeOpacity="0.22"
          fill="none"
        />

        {/* Outer Orbiting Satellite */}
        <g className="orbit-track-outer">
          <circle cx="20" cy="5" r={isCompact ? 3 : 2.6} fill="currentColor" />
        </g>

        {/* For sizes > 16px, add a complementary concentric inner orbit */}
        {!isCompact && (
          <>
            <circle
              cx="20"
              cy="20"
              r="9"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeOpacity="0.16"
              fill="none"
            />
            <g className="orbit-track-inner">
              <circle cx="20" cy="11" r="2.2" fill="currentColor" />
            </g>
          </>
        )}
      </svg>

      {label && (
        <span
          className={`orbit-loader-label ${
            pixelSize <= 14
              ? 'orbit-loader-label--inline'
              : pixelSize >= 40
              ? 'orbit-loader-label--lg'
              : ''
          }`}
        >
          {label}
        </span>
      )}
    </div>
  );
};

export default OrbitLoader;
