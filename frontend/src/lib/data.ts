/**
 * Xiphos vendor data module.
 *
 * In standalone (offline) mode, starts with an empty portfolio.
 * Users add vendors via the "Screen Vendor" tab.
 *
 * When connected to the API, cases are loaded from the backend database.
 */

import type { VettingCase, Alert } from "./types";

/** Start clean -- no pre-loaded vendors */
export const CASES: VettingCase[] = [];
export const ALERTS: Alert[] = [];
