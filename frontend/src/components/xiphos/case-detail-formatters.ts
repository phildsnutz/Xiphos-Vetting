export function fmtContrib(s: number): string {
  const pp = Math.abs(s * 100).toFixed(1);
  return s > 0 ? `+${pp} pp` : s < 0 ? `\u2212${pp} pp` : `${pp} pp`;
}
