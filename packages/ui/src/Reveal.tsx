import { motion, type HTMLMotionProps } from "motion/react";
import type { ReactNode } from "react";
import { DURATIONS, EASE_OUT } from "./motion-tokens";
import { useOneShotIntersection, usePrefersReducedMotion } from "./hooks";

interface RevealProps {
  children: ReactNode;
  delayMs?: number;
  className?: string;
  style?: React.CSSProperties;
}

function revealMotion(reduced: boolean, visible: boolean, delayMs: number): HTMLMotionProps<"div"> {
  if (!visible) {
    return {};
  }
  if (reduced) {
    return { animate: { opacity: 1 }, transition: { duration: DURATIONS.instant / 1000 } };
  }
  return {
    animate: { opacity: 1, translateY: 0 },
    transition: { duration: DURATIONS.base / 1000, ease: EASE_OUT, delay: delayMs / 1000 },
  };
}

export function Reveal({ children, delayMs = 0, className, style }: RevealProps) {
  const reduced = usePrefersReducedMotion();
  const { ref, visible } = useOneShotIntersection<HTMLDivElement>();
  const initial = reduced ? { opacity: 0 } : { opacity: 0, translateY: 24 };

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={initial}
      {...revealMotion(reduced, visible, delayMs)}
      {...(style !== undefined ? { style } : {})}
    >
      {children}
    </motion.div>
  );
}

export function PageStagger({ children, maxItems = 6 }: { children: ReactNode[]; maxItems?: number }) {
  return (
    <>
      {children.slice(0, maxItems).map((child, index) => (
        <Reveal key={index} delayMs={index * 40}>
          {child}
        </Reveal>
      ))}
      {children.length > maxItems ? <Reveal delayMs={maxItems * 40}>{children.slice(maxItems)}</Reveal> : null}
    </>
  );
}
