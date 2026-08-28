import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import {
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactElement,
  type Ref,
  type SyntheticEvent,
} from "react";

import { cn } from "./cn";

const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--mosaic-radius-control)] border border-transparent px-4 text-sm font-semibold transition-[transform,background-color,border-color,opacity] duration-[var(--mosaic-motion-fast)] ease-[var(--mosaic-motion-ease)] active:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 focus-visible:z-10",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--mosaic-color-accent)] text-[var(--mosaic-color-surface)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))]",
        secondary:
          "border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] text-[var(--mosaic-color-ink)] hover:bg-[var(--mosaic-color-surface-muted)]",
        danger:
          "bg-[var(--mosaic-color-danger)] text-[var(--mosaic-color-surface)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-danger)_88%,var(--mosaic-color-ink))]",
        ghost:
          "text-[var(--mosaic-color-ink)] hover:bg-[var(--mosaic-color-surface-muted)]",
      },
    },
    defaultVariants: {
      variant: "primary",
    },
  },
);

type ButtonVariantProps = VariantProps<typeof buttonVariants>;

export type NativeButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  ButtonVariantProps & {
    asChild?: false;
    loading?: boolean;
  };

export type SlottedButtonProps = Omit<
  HTMLAttributes<HTMLElement>,
  "children" | "className"
> &
  ButtonVariantProps & {
    /** Use a single non-button element, such as an anchor or Next Link. */
    asChild: true;
    children: ReactElement;
    className?: string;
    disabled?: boolean;
    loading?: boolean;
    type?: never;
  };

export type ButtonProps = NativeButtonProps | SlottedButtonProps;

/*
 * The forwarded ref is intentionally HTMLElement: a slotted child can be an
 * anchor, a framework Link, or another custom element. Native consumers still
 * receive the actual HTMLButtonElement at runtime.
 */

function stopActivation(event: SyntheticEvent<HTMLElement>) {
  event.preventDefault();
  event.stopPropagation();
}

export const Button = forwardRef<HTMLElement, ButtonProps>(function Button(
  {
    asChild = false,
    loading = false,
    variant,
    className,
    disabled = false,
    children,
    onClick,
    onClickCapture,
    onKeyDownCapture,
    onPointerDownCapture,
    tabIndex,
    type,
    ...props
  },
  ref,
) {
  const isDisabled = disabled || loading;
  const classes = cn(buttonVariants({ variant }), className);

  if (asChild) {
    if (!isValidElement(children)) {
      throw new Error(
        "Button asChild expects a single non-button element child.",
      );
    }
    if (children.type === "button") {
      throw new Error(
        "Button asChild does not support native <button> children; render Button without asChild.",
      );
    }

    return (
      <Slot
        ref={ref}
        {...props}
        className={classes}
        aria-busy={loading || undefined}
        aria-disabled={isDisabled || undefined}
        tabIndex={isDisabled ? -1 : tabIndex}
        onClick={isDisabled ? undefined : onClick}
        onClickCapture={isDisabled ? stopActivation : onClickCapture}
        onKeyDownCapture={isDisabled ? stopActivation : onKeyDownCapture}
        onPointerDownCapture={
          isDisabled ? stopActivation : onPointerDownCapture
        }
      >
        {children}
      </Slot>
    );
  }

  return (
    <button
      ref={ref as Ref<HTMLButtonElement>}
      {...props}
      className={classes}
      disabled={isDisabled || undefined}
      aria-busy={loading || undefined}
      tabIndex={tabIndex}
      type={type ?? "button"}
      onClick={onClick}
      onClickCapture={onClickCapture}
      onKeyDownCapture={onKeyDownCapture}
      onPointerDownCapture={onPointerDownCapture}
    >
      {children}
    </button>
  );
});

Button.displayName = "Button";
