import { motion, useScroll, useTransform } from "motion/react";
import { useRef, useState } from "react";
import { usePrefersReducedMotion } from "./hooks";

export interface SpineNodeData {
  id: string;
  label: string;
  kind: "score" | "field";
  value?: string;
  quote: string;
  meta?: Record<string, string>;
}

interface EvidenceSpineProps {
  nodes: SpineNodeData[];
  activeId?: string;
  onSelect?: (id: string) => void;
}

interface NodeProps {
  node: SpineNodeData;
  expanded: boolean;
  onToggle: () => void;
}

function SpineNodeRow({ node, expanded, onToggle }: NodeProps) {
  return (
    <li className="relative pl-10">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="group absolute left-0 top-1 grid h-7 w-7 place-items-center rounded-full border border-[var(--steel)] bg-[var(--hull)] transition-colors hover:border-[var(--signal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
      >
        <span
          className={
            node.kind === "score"
              ? "block h-2.5 w-2.5 rounded-full bg-[var(--signal)]"
              : "block h-2 w-2 rotate-45 border border-[var(--signal-text)] bg-transparent group-hover:bg-[var(--signal-dim)]"
          }
        />
        <span className="sr-only">{`Toggle evidence for ${node.label}`}</span>
      </button>

      <div className="pb-8">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="flex w-full flex-col items-start gap-1 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--signal)]"
        >
          <span className="text-xs font-medium uppercase tracking-wide text-[var(--haze)]">
            {node.label}
          </span>
          {node.value ? (
            <span className="data-value text-lg font-semibold text-[var(--mist)]">
              {node.value}
            </span>
          ) : null}
        </button>

        {expanded ? (
          <motion.div
            initial={false}
            animate={{ opacity: 1 }}
            className="mt-3 max-w-xl rounded-[var(--radius-md)] border border-[var(--steel)] bg-[var(--abyss)] p-4"
          >
            <blockquote className="border-l-2 border-[var(--signal)] pl-3 text-sm italic leading-relaxed text-[var(--mist)]">
              “{node.quote}”
            </blockquote>
            {node.meta ? (
              <dl className="mono mt-3 grid gap-x-6 gap-y-1 text-xs text-[var(--haze)] sm:grid-cols-2">
                {Object.entries(node.meta).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-3">
                    <dt>{key}</dt>
                    <dd className="text-right text-[var(--mist)]">{value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </motion.div>
        ) : null}
      </div>
    </li>
  );
}

export function EvidenceSpine({ nodes, activeId, onSelect }: EvidenceSpineProps) {
  const reduced = usePrefersReducedMotion();
  const containerRef = useRef<HTMLOListElement>(null);
  const [internalOpen, setInternalOpen] = useState<string | null>(null);
  const openId = activeId ?? internalOpen;

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start 80%", "end 60%"],
  });
  const pathLength = useTransform(scrollYProgress, (v) => v);
  const staticLength = reduced ? 1 : pathLength;

  if (nodes.length === 0) {
    return (
      <p role="status" className="text-sm text-[var(--haze)]">
        No scored dimensions yet.
      </p>
    );
  }

  return (
    <ol ref={containerRef} className="relative m-0 list-none p-0">
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute left-[13px] top-0 h-full w-[2px] overflow-visible"
        preserveAspectRatio="none"
        viewBox="0 0 2 100"
      >
        <line x1="1" y1="0" x2="1" y2="100" stroke="var(--steel)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <motion.line
          x1="1"
          y1="0"
          x2="1"
          y2="100"
          stroke="var(--signal)"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          style={{ pathLength: staticLength }}
        />
      </svg>
      {nodes.map((node) => (
        <SpineNodeRow
          key={node.id}
          node={node}
          expanded={openId === node.id}
          onToggle={() => {
            setInternalOpen(openId === node.id ? null : node.id);
            onSelect?.(node.id);
          }}
        />
      ))}
    </ol>
  );
}
