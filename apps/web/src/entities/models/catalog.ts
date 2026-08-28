/**
 * Frontend-owned visual metadata. These types deliberately contain no
 * provider, deployment, revision, or execution details.
 */
export type ModelCardMedia =
  | { kind: "abstract"; src: string; alt: string }
  | { kind: "gallery"; sources: readonly { src: string; alt: string }[] }
  | { kind: "video"; src: string; alt: string }
  | { kind: "audio"; waveform: readonly number[]; durationLabel: string }
  | { kind: "none" };

export interface ModelPresentation {
  productModelId: string;
  cardStyle: "hero" | "gallery" | "video" | "audio" | "compact";
  media: ModelCardMedia;
  actionLabel: string;
}
