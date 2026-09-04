import { forwardRef } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "action" | "ghost" | "danger";

const buttonStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--signal)] text-white shadow-sm hover:bg-[var(--signal-text)] focus-visible:outline-[var(--signal-text)]",
  action: "bg-[var(--ember)] text-white shadow-sm hover:brightness-110 focus-visible:outline-[var(--ember)]",
  ghost:
    "bg-transparent text-[var(--mist)] border border-[var(--steel)] hover:border-[var(--signal)] hover:text-[var(--signal-text)] focus-visible:outline-[var(--signal)]",
  danger: "bg-transparent text-[var(--danger)] border border-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_15%,transparent)] focus-visible:outline-[var(--danger)]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Trailing arrow affordance for feature-card CTAs. */
  arrow?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", arrow = false, className, type = "button", children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "group inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--radius-md)] px-4",
        "font-semibold transition-colors duration-[var(--dur-quick)]",
        "focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:pointer-events-none disabled:opacity-50",
        buttonStyles[variant],
        className,
      )}
      {...rest}
    >
      {children}
      {arrow ? (
        <span
          aria-hidden="true"
          className="transition-transform duration-[var(--dur-quick)] group-hover:translate-x-0.5"
        >
          →
        </span>
      ) : null}
    </button>
  );
});

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  htmlFor: string;
}

export function Field({ label, hint, error, children, htmlFor }: FieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="text-xs font-semibold uppercase tracking-wide text-[var(--haze)]"
      >
        {label}
      </label>
      {children}
      {hint && !error ? <span className="text-xs text-[var(--haze)]">{hint}</span> : null}
      {error ? (
        <span role="alert" className="text-xs text-[var(--danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

const controlClasses = cn(
  "w-full rounded-[var(--radius-md)] border border-[var(--steel)] bg-[var(--hull)] px-3 py-2.5",
  "text-base text-[var(--mist)] placeholder:text-[var(--haze)]",
  "focus:border-[var(--signal)] focus:outline-none focus:ring-2 focus:ring-[var(--signal)]/40",
  "disabled:opacity-50",
);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(controlClasses, "min-h-11", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return <textarea ref={ref} className={cn(controlClasses, "min-h-24 resize-y", className)} {...rest} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select
        ref={ref}
        className={cn(controlClasses, "min-h-11 appearance-none bg-no-repeat pr-9", className)}
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%238fa3bc' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E\")",
          backgroundPosition: "right 0.75rem center",
          backgroundSize: "1rem",
        }}
        {...rest}
      >
        {children}
      </select>
    );
  },
);

interface CardProps {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}

export function Card({ children, className, interactive = false }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--steel)] bg-[var(--hull)] p-6 shadow-sm",
        interactive &&
          "cursor-pointer transition-all duration-[var(--dur-quick)] hover:-translate-y-0.5 hover:border-[var(--signal)] hover:shadow-md focus-within:border-[var(--signal)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

type BadgeTone = "neutral" | "positive" | "warning" | "negative" | "accent";

const badgeTones: Record<BadgeTone, string> = {
  neutral: "border-[var(--steel)] text-[var(--haze)]",
  positive: "border-[var(--success)] text-[var(--success)]",
  warning: "border-[var(--warning)] text-[var(--warning)]",
  negative: "border-[var(--danger)] text-[var(--danger)]",
  accent: "border-[var(--signal)] text-[var(--signal-text)]",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[var(--radius-full)] border px-2.5 py-0.5 text-xs font-medium",
        badgeTones[tone],
      )}
    >
      {children}
    </span>
  );
}

interface EmptyStateProps {
  title: string;
  body: string;
  action?: ReactNode;
}

export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-[var(--radius-lg)] border border-dashed border-[var(--steel)] px-8 py-12 text-center"
    >
      <h2 className="display text-lg font-semibold">{title}</h2>
      <p className="text-sm text-[var(--haze)]">{body}</p>
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "animate-pulse rounded-[var(--radius-md)] bg-[var(--steel)]/60 motion-reduce:animate-none",
        className,
      )}
    />
  );
}
