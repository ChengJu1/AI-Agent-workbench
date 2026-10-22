// The one place the workbench shell learns which kits exist.
import { jobSearchKit } from "./jobSearch";
import type { Kit } from "./types";

export const KITS: Kit[] = [jobSearchKit];

export const kitsFor = (capabilities: readonly string[] | undefined) => KITS.filter(kit => capabilities?.includes(kit.capability));
