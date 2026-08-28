export interface RouteStateProps {
  title: string;
  description?: string;
}

export function RouteState({ title, description }: RouteStateProps) {
  return (
    <section className="grid gap-6">
      <div className="max-w-3xl">
        <h1 className="[font-size:var(--mosaic-typography-h1-font-size)] font-semibold [line-height:var(--mosaic-typography-h1-line-height)] tracking-[-0.04em] text-[var(--mosaic-color-ink)]">
          {title}
        </h1>
        {description ? (
          <p className="mt-3 max-w-[65ch] text-[var(--mosaic-color-ink-muted)]">
            {description}
          </p>
        ) : null}
      </div>
    </section>
  );
}
