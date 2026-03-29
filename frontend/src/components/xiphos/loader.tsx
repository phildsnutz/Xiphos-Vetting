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
      className="rounded animate-pulse"
      style={{
        height,
        background: T.raised,
        opacity: 0.6,
      }}
    />
  );
}
