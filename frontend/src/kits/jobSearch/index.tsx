// Job-search kit: what the workbench shell shows when an Agent has the ledger capability.
import { lazy } from "react";
import type { Kit } from "../types";
import { DailyBrief } from "./DailyBrief";
import { LedgerButton } from "./LedgerButton";
import { JOB_SEARCH_MANIFEST } from "./manifest";

const ApplicationCenter = lazy(() => import("./ApplicationCenter").then(m => ({ default: m.ApplicationCenter })));

export const jobSearchKit: Kit = {
  capability: JOB_SEARCH_MANIFEST.capability,
  HeaderButton: ({ disabled, onOpen }) => <LedgerButton disabled={disabled} onClick={() => onOpen()} />,
  Dialog: ({ itemId, onClose }) => <ApplicationCenter initialId={itemId} onClose={onClose} />,
  Welcome: ({ onOpen, onOpenTracking }) => <DailyBrief onOpenApplication={onOpen} onOpenTracking={onOpenTracking} />,
};
