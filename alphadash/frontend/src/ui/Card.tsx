import type { JSX, ReactNode } from "react";
import { createElement } from "react";

import { color, radius, space } from "./tokens";

// Frozen contract (S0.4):
export interface CardProps {
  children: ReactNode;
  padded?: boolean;
  as?: keyof JSX.IntrinsicElements;
}

export function Card({ children, padded = true, as = "section" }: CardProps) {
  return createElement(
    as,
    {
      style: {
        background: color.surface,
        border: `1px solid ${color.border}`,
        borderRadius: radius.lg,
        padding: padded ? space.lg : 0,
      },
    },
    children,
  );
}
