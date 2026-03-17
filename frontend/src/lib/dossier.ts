/**
 * Client-side dossier generation.
 * Produces a self-contained HTML document styled for print/PDF export.
 * User can Ctrl+P to save as PDF from the browser.
 */

import type { VettingCase } from "./types";
import { TIER_META, tierColor } from "./tokens";

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function fmtPct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

function fmtContrib(s: number): string {
  const pp = Math.abs(s * 100).toFixed(1);
  return s > 0 ? `+${pp} pp` : s < 0 ? `\u2212${pp} pp` : `${pp} pp`;
}

export function generateDossierHTML(c: VettingCase): string {
  const cal = c.cal;
  const tierLabel = cal ? TIER_META[cal.tier]?.label ?? cal.tier : "PENDING";
  const tierColorValue = cal ? tierColor(cal.tier) : "#64748b";

  const now = new Date().toISOString().split("T")[0];

  let hardStopsHTML = "";
  if (cal?.stops?.length) {
    hardStopsHTML = `
      <div class="alert critical">
        <h3>HARD STOP TRIGGERS</h3>
        ${cal.stops.map((s) => `
          <div class="stop-item">
            <strong>${esc(s.t)}</strong>
            <p>${esc(s.x)}</p>
            <span class="conf">Confidence: ${fmtPct(s.c)}</span>
          </div>
        `).join("")}
      </div>`;
  }

  let flagsHTML = "";
  if (cal?.flags?.length) {
    flagsHTML = `
      <div class="alert warning">
        <h3>ADVISORY FLAGS</h3>
        ${cal.flags.map((f) => `
          <div class="flag-item">
            <strong>${esc(f.t)}</strong>
            <p>${esc(f.x)}</p>
            <span class="conf">Confidence: ${fmtPct(f.c)}</span>
          </div>
        `).join("")}
      </div>`;
  }

  let contribHTML = "";
  if (cal?.ct?.length) {
    const sorted = [...cal.ct].sort((a, b) => Math.abs(b.s) - Math.abs(a.s));
    contribHTML = `
      <h2>Risk Factor Analysis</h2>
      <table class="factors">
        <thead>
          <tr>
            <th>Factor</th>
            <th>Raw Score</th>
            <th>Contribution</th>
            <th>Confidence</th>
            <th>Assessment</th>
          </tr>
        </thead>
        <tbody>
          ${sorted.map((ct) => `
            <tr>
              <td><strong>${esc(ct.n)}</strong></td>
              <td class="mono">${(ct.raw * 100).toFixed(0)}/100</td>
              <td class="mono ${ct.s > 0 ? "risk-up" : "risk-down"}">${fmtContrib(ct.s)}</td>
              <td class="mono">${fmtPct(ct.c)}</td>
              <td>${esc(ct.d)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }

  let findingsHTML = "";
  if (cal?.finds?.length) {
    findingsHTML = `
      <h2>Key Findings</h2>
      <ol>
        ${cal.finds.map((f) => `<li>${esc(f)}</li>`).join("")}
      </ol>`;
  }

  let mivHTML = "";
  if (cal?.miv?.length) {
    mivHTML = `
      <h2>Recommended Data Collection</h2>
      <table class="miv">
        <thead>
          <tr><th>Action</th><th>Expected Impact</th><th>Tier Change Prob</th></tr>
        </thead>
        <tbody>
          ${cal.miv.map((m) => `
            <tr>
              <td>${esc(m.t)}</td>
              <td class="mono">${m.i.toFixed(1)} pp</td>
              <td class="mono">${fmtPct(m.tp)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>XIPHOS Dossier: ${esc(c.name)}</title>
<style>
  @page { margin: 1in; size: letter; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11px; line-height: 1.6; color: #1a1a1a;
    max-width: 800px; margin: 0 auto; padding: 40px 20px;
  }
  .header {
    border-bottom: 3px solid #0a0e17;
    padding-bottom: 16px; margin-bottom: 24px;
  }
  .header h1 { font-size: 20px; margin-bottom: 4px; }
  .header .subtitle { font-size: 11px; color: #666; }
  .classification {
    display: inline-block; padding: 3px 10px; border-radius: 3px;
    font-weight: 700; font-size: 11px; letter-spacing: 0.1em;
    color: white; margin-top: 8px;
  }
  .meta-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 4px 24px; margin: 16px 0;
    font-size: 11px;
  }
  .meta-grid dt { color: #666; }
  .meta-grid dd { font-weight: 600; margin-left: 0; }
  .score-box {
    display: flex; gap: 40px; padding: 16px;
    background: #f8f9fa; border: 1px solid #e2e8f0;
    border-radius: 6px; margin: 16px 0;
  }
  .score-item { text-align: center; }
  .score-item .value { font-size: 28px; font-weight: 700; font-family: monospace; }
  .score-item .label { font-size: 9px; color: #666; text-transform: uppercase; letter-spacing: 0.1em; }
  h2 { font-size: 14px; margin: 24px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 10px; }
  th { text-align: left; padding: 6px 8px; background: #f1f5f9; border-bottom: 2px solid #e2e8f0; font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em; }
  td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; }
  .mono { font-family: monospace; }
  .risk-up { color: #dc2626; }
  .risk-down { color: #16a34a; }
  .alert { padding: 12px 16px; border-radius: 6px; margin: 12px 0; }
  .alert.critical { background: #fef2f2; border: 1px solid #fecaca; }
  .alert.critical h3 { color: #dc2626; font-size: 12px; margin-bottom: 6px; }
  .alert.warning { background: #fffbeb; border: 1px solid #fde68a; }
  .alert.warning h3 { color: #d97706; font-size: 12px; margin-bottom: 6px; }
  .stop-item, .flag-item { margin: 8px 0; }
  .conf { font-size: 9px; color: #888; font-family: monospace; }
  ol { padding-left: 20px; }
  li { margin: 4px 0; }
  .footer {
    margin-top: 40px; padding-top: 12px;
    border-top: 1px solid #e2e8f0;
    font-size: 9px; color: #999;
    display: flex; justify-content: space-between;
  }
  @media print {
    body { padding: 0; }
    .no-print { display: none; }
  }
</style>
</head>
<body>
  <div class="no-print" style="background:#3b82f6;color:white;padding:8px 16px;border-radius:6px;margin-bottom:24px;font-size:12px;text-align:center;">
    Press Ctrl+P (or Cmd+P) to save as PDF
  </div>

  <div class="header">
    <h1>XIPHOS Vendor Intelligence Dossier</h1>
    <div class="subtitle">Automated risk assessment generated ${now}</div>
    <div class="classification" style="background:${tierColorValue}">
      ${tierLabel}
    </div>
  </div>

  <dl class="meta-grid">
    <dt>Vendor</dt><dd>${esc(c.name)}</dd>
    <dt>Country</dt><dd>${esc(c.cc)}</dd>
    <dt>Case ID</dt><dd>${esc(c.id)}</dd>
    <dt>Assessment Date</dt><dd>${esc(c.date)}</dd>
    <dt>Rubric Score</dt><dd>${c.sc}/100</dd>
    <dt>Rubric Confidence</dt><dd>${fmtPct(c.conf)}</dd>
  </dl>

  ${cal ? `
  <div class="score-box">
    <div class="score-item">
      <div class="value" style="color:${tierColorValue}">${fmtPct(cal.p)}</div>
      <div class="label">Bayesian Posterior</div>
    </div>
    <div class="score-item">
      <div class="value">${fmtPct(cal.lo)}&ndash;${fmtPct(cal.hi)}</div>
      <div class="label">95% Confidence Interval</div>
    </div>
    <div class="score-item">
      <div class="value">${fmtPct(cal.cov)}</div>
      <div class="label">Coverage</div>
    </div>
    <div class="score-item">
      <div class="value">${c.sc}</div>
      <div class="label">Policy Rubric</div>
    </div>
  </div>
  ` : ""}

  ${hardStopsHTML}
  ${flagsHTML}
  ${contribHTML}
  ${findingsHTML}
  ${mivHTML}

  <div class="footer">
    <span>XIPHOS Dual-Engine Vendor Vetting System</span>
    <span>CONFIDENTIAL -- Generated ${now}</span>
  </div>
</body>
</html>`;
}

/**
 * Generate and open a dossier in a new tab.
 */
export function openDossier(c: VettingCase): void {
  const html = generateDossierHTML(c);
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  // Clean up after a delay
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
