/**
 * Lightweight telemetry helper for Sprint 10.5 event coverage expansion.
 *
 * Fire-and-forget wrapper around trackBetaEvent. Components import `emit`
 * and call it without awaiting or catching. Failures are silently swallowed
 * so telemetry never blocks UI interactions.
 *
 * Event naming convention: snake_case, verb_noun, e.g.
 *   "graph_entity_clicked", "provenance_viewed", "monitor_triggered"
 */

import { trackBetaEvent } from "./api";
import type { WorkflowLane } from "@/components/xiphos/portfolio-utils";

interface EmitOptions {
  workflow_lane?: WorkflowLane;
  screen?: string;
  case_id?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Fire-and-forget telemetry event.
 * Safe to call in click handlers, useEffects, etc. without awaiting.
 */
export function emit(eventName: string, opts: EmitOptions = {}): void {
  void trackBetaEvent({
    event_name: eventName,
    workflow_lane: opts.workflow_lane,
    screen: opts.screen,
    case_id: opts.case_id,
    metadata: opts.metadata,
  }).catch(() => undefined);
}
