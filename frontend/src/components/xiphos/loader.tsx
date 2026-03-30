import { T } from "@/lib/tokens";

export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center">
      <div
        className="animate-spin rounded-full"
        style={{
          width: 24,
          height: 24,
          border: `3px solid ${T.border}`,
          borderTop: `3px solid ${T.accent}`,
        }}
      />
    </div>
  );
}

export function LoadingSkeleton({ height = 24 }: { height?: number }) {
  return (
    <div
      className="rounded skeleton-pulse"
      style={{
        height,
        background: T.raised,
      }}
    />
  );
}

/** Skeleton card that mimics a metric card during loading */
export function SkeletonCard({ lines = 2 }: { lines?: number }) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ background: T.surface, border: `1px solid ${T.border}` }}
    >
      <div className="skeleton-pulse rounded" style={{ height: 10, width: "50%", marginBottom: 10 }} />
      <div className="skeleton-pulse rounded" style={{ height: 22, width: "40%", marginBottom: lines > 1 ? 8 : 0 }} />
      {lines > 1 && <div className="skeleton-pulse rounded" style={{ height: 10, width: "70%" }} />}
    </div>
  );
}

/** Skeleton grid that mimics the metric card grid */
export function SkeletonMetricGrid({ count = 8 }: { count?: number }) {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

/** Skeleton for queue items */
export function SkeletonQueueItem() {
  return (
    <div
      className="rounded-lg p-3"
      style={{ background: T.bg, border: `1px solid ${T.border}` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div style={{ flex: 1 }}>
          <div className="skeleton-pulse rounded" style={{ height: 14, width: "60%", marginBottom: 8 }} />
          <div className="skeleton-pulse rounded" style={{ height: 11, width: "45%" }} />
        </div>
        <div className="flex items-center gap-2">
          <div className="skeleton-pulse rounded-full" style={{ height: 22, width: 48 }} />
          <div className="skeleton-pulse rounded-full" style={{ height: 22, width: 80 }} />
        </div>
      </div>
      <div className="flex items-center gap-2" style={{ marginTop: 10 }}>
        <div className="skeleton-pulse rounded" style={{ height: 30, width: 80 }} />
        <div className="skeleton-pulse rounded" style={{ height: 30, width: 70 }} />
      </div>
    </div>
  );
}
