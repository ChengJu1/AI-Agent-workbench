import type { ComponentType } from "react";
import type { KitCapability } from "./manifests";

/** The specialised part of one kind of Agent, shown by the shell only when the Agent has the kit's capability. */
export type Kit = {
  capability: KitCapability;
  /** Entry in the header tools. */
  HeaderButton?: ComponentType<{ disabled: boolean; onOpen: (itemId?: string) => void }>;
  /** The kit's own dialog; itemId opens a specific record. */
  Dialog?: ComponentType<{ itemId?: string; onClose: () => void }>;
  /** Panel above the welcome prompts of a new conversation. */
  Welcome?: ComponentType<{ onOpen: (itemId?: string) => void; onOpenTracking: () => void }>;
};
