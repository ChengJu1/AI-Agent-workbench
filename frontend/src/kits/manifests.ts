// Plain-data manifests of every kit; safe to import from core modules (no components, no styles).
import { JOB_SEARCH_MANIFEST } from "./jobSearch/manifest.ts";

export const KIT_MANIFESTS = [JOB_SEARCH_MANIFEST] as const;
export type KitCapability = (typeof KIT_MANIFESTS)[number]["capability"];
