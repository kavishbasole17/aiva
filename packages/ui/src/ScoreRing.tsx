import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import { useEffect } from "react";
import { usePrefersReducedMotion } from "./hooks";
import { SPRING } from "./motion-tokens";

interface ScoreRingProps {
  score: number;
  max?: number;
  label: string;
  sizePx?: number;
}

export function ScoreRing({ score, max = 100, label, sizePx = 96 }: ScoreRingProps) {
  const reduced = usePrefersReducedMotion();
  const clamped = Math.max(0, Math.min(max, score));
  const fraction = clamped / max;

  const raw = useMotionValue(reduced ? fraction : 0);
  const spring = useSpring(raw, SPRING);
  const dashOffset = useTransform(spring, (value) => (1 - value) * 100);

  useEffect(() => {
    raw.set(fraction);
  }, [fraction, raw]);

  return (
    <div
      role="meter"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
      style={{
        width: sizePx,
        height: sizePx,
        position: "relative",
        display: "inline-grid",
        placeItems: "center",
      }}
    >
      <svg width={sizePx} height={sizePx} viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--steel)" strokeWidth="8" />
        <motion.circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="var(--signal)"
          strokeWidth="8"
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray="100"
          style={{ strokeDashoffset: reduced ? (1 - fraction) * 100 : dashOffset }}
          transform="rotate(-90 50 50)"
        />
      </svg>
      <span
        className="data-value"
        style={{ position: "absolute", fontSize: "var(--text-lg)", color: "var(--mist)" }}
      >
        {Math.round(clamped)}
      </span>
      <span style={{ position: "absolute", bottom: -18, fontSize: "var(--text-xs)", color: "var(--haze)" }}>
        {label}
      </span>
    </div>
  );
}
