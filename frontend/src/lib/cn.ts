import clsx, { type ClassValue } from "clsx";

/** Tiny className helper (re-exports clsx). */
export function cn(...values: ClassValue[]): string {
  return clsx(values);
}
