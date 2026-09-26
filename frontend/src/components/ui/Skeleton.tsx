import { cn } from "@/lib/cn";

/** Subtle animated placeholder block. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse-soft rounded-md bg-surface-alt",
        className,
      )}
    />
  );
}
