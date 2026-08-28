import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "./cn";

export interface InputFieldProps
  extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  description?: string;
  error?: string;
}

export const InputField = forwardRef<HTMLInputElement, InputFieldProps>(
  function InputField(
    {
      id,
      label,
      description,
      error,
      className,
      "aria-describedby": callerDescribedBy,
      ...props
    },
    ref,
  ) {
    const generatedDescribedBy = [
      description ? `${id}-description` : undefined,
      error ? `${id}-error` : undefined,
    ].filter((value): value is string => Boolean(value));
    const describedBy = [
      ...(callerDescribedBy?.split(/\s+/).filter(Boolean) ?? []),
      ...generatedDescribedBy,
    ]
      .filter((value, index, values) => values.indexOf(value) === index)
      .join(" ");

    return (
      <div className="grid gap-2">
        <label
          htmlFor={id}
          className="text-sm font-semibold text-[var(--mosaic-color-ink)]"
        >
          {label}
        </label>
        <input
          {...props}
          ref={ref}
          id={id}
          aria-describedby={describedBy || undefined}
          aria-invalid={error ? true : undefined}
          className={cn(
            "min-h-11 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-3 text-[var(--mosaic-color-ink)] placeholder:text-[var(--mosaic-color-ink-muted)] transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)]",
            error && "border-[var(--mosaic-color-danger)]",
            className,
          )}
        />
        {description ? (
          <p
            id={`${id}-description`}
            className="text-sm text-[var(--mosaic-color-ink-muted)]"
          >
            {description}
          </p>
        ) : null}
        {error ? (
          <p
            id={`${id}-error`}
            className="text-sm text-[var(--mosaic-color-danger)]"
          >
            {error}
          </p>
        ) : null}
      </div>
    );
  },
);

InputField.displayName = "InputField";
