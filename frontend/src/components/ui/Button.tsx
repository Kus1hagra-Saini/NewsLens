import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const VARIANT_CLS: Record<Variant, string> = {
  primary:
    "bg-ink-primary text-canvas hover:bg-accent-strong " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]",
  secondary:
    "bg-surface text-ink-primary border border-subtle " +
    "hover:border-strong hover:bg-surface-alt",
  ghost:
    "text-ink-secondary hover:text-ink-primary hover:bg-surface-alt",
};

const SIZE_CLS: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = "primary", size = "md", className, ...rest },
    ref,
  ) {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2",
          "rounded-full font-medium select-none",
          "transition-colors duration-150 ease-soft",
          "disabled:opacity-50 disabled:pointer-events-none",
          VARIANT_CLS[variant],
          SIZE_CLS[size],
          className,
        )}
        {...rest}
      />
    );
  },
);
