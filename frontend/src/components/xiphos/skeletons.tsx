import React from 'react';
import { T, SP, MOTION } from '../../lib/tokens';

/**
 * Skeleton Loading Components
 *
 * Shimmer-based skeleton screens to replace spinners/blank states.
 * All components use design tokens and include inline animations.
 */

// Inline shimmer animation
const shimmerStyles = `
  @keyframes shimmer {
    0% {
      background-color: ${T.surface};
    }
    50% {
      background-color: ${T.surfaceElevated};
    }
    100% {
      background-color: ${T.surface};
    }
  }
  .skeleton-shimmer {
    animation: shimmer ${MOTION.slow} ease-in-out infinite;
  }
`;

// Inject animation styles into the document
if (typeof document !== 'undefined') {
  const style = document.createElement('style');
  style.textContent = shimmerStyles;
  if (!document.head.querySelector('style[data-skeleton]')) {
    style.setAttribute('data-skeleton', 'true');
    document.head.appendChild(style);
  }
}

// ============================================================================
// SkeletonBlock - Base building block
// ============================================================================

interface SkeletonBlockProps {
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

export const SkeletonBlock: React.FC<SkeletonBlockProps> = ({
  width = '100%',
  height = '20px',
  borderRadius = '4px',
  className = '',
  style = {},
}) => {
  return (
    <div
      className={`skeleton-shimmer ${className}`}
      style={{
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height,
        borderRadius: typeof borderRadius === 'number' ? `${borderRadius}px` : borderRadius,
        border: `1px solid ${T.border}`,
        ...style,
      }}
    />
  );
};

// ============================================================================
// SkeletonText - Text line placeholder
// ============================================================================

interface SkeletonTextProps {
  lines?: number;
  width?: string;
}

export const SkeletonText: React.FC<SkeletonTextProps> = ({ lines = 3, width = '100%' }) => {
  const widths = ['100%', '85%', '70%', '95%', '80%', '75%'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: `${SP.sm}px` }}>
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBlock
          key={i}
          width={i === 0 ? width : widths[i % widths.length]}
          height="16px"
          borderRadius="4px"
        />
      ))}
    </div>
  );
};

// ============================================================================
// CaseDetailSkeleton - Case detail page loading
// ============================================================================

export const CaseDetailSkeleton: React.FC = () => {
  return (
    <div className="animate-fade-in" style={{ padding: `${SP.lg}px` }}>
      {/* Header area */}
      <div style={{ marginBottom: `${SP.xl}px` }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: `${SP.md}px`,
            marginBottom: `${SP.md}px`,
          }}
        >
          {/* Title bar */}
          <SkeletonBlock width="50%" height="32px" borderRadius="6px" />
          {/* Badge */}
          <SkeletonBlock width="80px" height="24px" borderRadius="4px" />
        </div>
        {/* Tier indicator */}
        <SkeletonBlock width="120px" height="20px" borderRadius="4px" />
      </div>

      {/* Lane selector tabs */}
      <div
        style={{
          display: 'flex',
          gap: `${SP.md}px`,
          marginBottom: `${SP.xl}px`,
          borderBottom: `1px solid ${T.border}`,
          paddingBottom: `${SP.md}px`,
        }}
      >
        {[1, 2, 3].map((i) => (
          <SkeletonBlock key={i} width="100px" height="20px" borderRadius="4px" />
        ))}
      </div>

      {/* Main content: 2-column layout */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: `${SP.lg}px`,
        }}
      >
        {/* Decision panel (left) */}
        <div>
          <SkeletonBlock width="100%" height="24px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonBlock
              key={i}
              width="100%"
              height="60px"
              borderRadius="6px"
              style={{ marginBottom: `${SP.md}px` }}
            />
          ))}
        </div>

        {/* Enrichment (right) */}
        <div>
          <SkeletonBlock width="100%" height="24px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBlock
              key={i}
              width="100%"
              height="80px"
              borderRadius="6px"
              style={{ marginBottom: `${SP.md}px` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// PortfolioSkeleton - Portfolio list loading
// ============================================================================

export const PortfolioSkeleton: React.FC = () => {
  return (
    <div className="animate-fade-in" style={{ padding: `${SP.lg}px` }}>
      {/* KPI cards row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: `${SP.md}px`,
          marginBottom: `${SP.xl}px`,
        }}
      >
        {[1, 2, 3, 4].map((i) => (
          <SkeletonBlock
            key={i}
            width="100%"
            height="100px"
            borderRadius="8px"
          />
        ))}
      </div>

      {/* Sort bar */}
      <div style={{ marginBottom: `${SP.lg}px` }}>
        <SkeletonBlock width="150px" height="24px" borderRadius="4px" />
      </div>

      {/* Case row blocks */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: `${SP.md}px` }}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <SkeletonBlock
            key={i}
            width={i % 2 === 0 ? '98%' : '100%'}
            height="56px"
            borderRadius="6px"
          />
        ))}
      </div>
    </div>
  );
};

// ============================================================================
// EnrichmentSkeleton - Enrichment panel loading
// ============================================================================

export const EnrichmentSkeleton: React.FC = () => {
  return (
    <div className="animate-fade-in" style={{ padding: `${SP.lg}px` }}>
      {/* KPI cards row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: `${SP.md}px`,
          marginBottom: `${SP.xl}px`,
        }}
      >
        {[1, 2, 3].map((i) => (
          <SkeletonBlock
            key={i}
            width="100%"
            height="80px"
            borderRadius="8px"
          />
        ))}
      </div>

      {/* Finding cards */}
      <div style={{ marginBottom: `${SP.xl}px` }}>
        <SkeletonBlock width="100px" height="20px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: `${SP.md}px` }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <SkeletonBlock
              key={i}
              width="100%"
              height="70px"
              borderRadius="6px"
            />
          ))}
        </div>
      </div>

      {/* Source status section */}
      <div>
        <SkeletonBlock width="120px" height="20px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: `${SP.md}px` }}>
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <SkeletonBlock
              key={i}
              width="100%"
              height="32px"
              borderRadius="4px"
            />
          ))}
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// GraphSkeleton - Entity graph loading
// ============================================================================

export const GraphSkeleton: React.FC = () => {
  return (
    <div className="animate-fade-in" style={{ padding: `${SP.lg}px`, display: 'flex', gap: `${SP.lg}px` }}>
      {/* Graph canvas area (large central area) */}
      <div style={{ flex: 1 }}>
        <SkeletonBlock
          width="100%"
          height="500px"
          borderRadius="8px"
        />
      </div>

      {/* Sidebar */}
      <div style={{ width: '250px' }}>
        <SkeletonBlock width="100%" height="24px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
        {[1, 2, 3].map((i) => (
          <SkeletonBlock
            key={i}
            width="100%"
            height="60px"
            borderRadius="6px"
            style={{ marginBottom: `${SP.md}px` }}
          />
        ))}
      </div>
    </div>
  );
};

// ============================================================================
// AIAnalysisSkeleton - AI analysis panel loading
// ============================================================================

export const AIAnalysisSkeleton: React.FC = () => {
  return (
    <div className="animate-fade-in" style={{ padding: `${SP.lg}px` }}>
      {/* Header with run button */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: `${SP.lg}px`,
        }}
      >
        <SkeletonBlock width="120px" height="24px" borderRadius="4px" />
        <SkeletonBlock width="100px" height="32px" borderRadius="6px" />
      </div>

      {/* Verdict badge */}
      <SkeletonBlock width="100px" height="28px" borderRadius="4px" style={{ marginBottom: `${SP.xl}px` }} />

      {/* Section blocks: executive summary, risk narrative, concerns, actions */}
      {[1, 2, 3, 4].map((i) => (
        <div key={i} style={{ marginBottom: `${SP.xl}px` }}>
          {/* Section title */}
          <SkeletonBlock width="150px" height="20px" borderRadius="4px" style={{ marginBottom: `${SP.md}px` }} />
          {/* Section content */}
          <SkeletonText lines={3} width="100%" />
        </div>
      ))}
    </div>
  );
};
