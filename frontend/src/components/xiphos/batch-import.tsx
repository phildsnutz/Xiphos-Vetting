import { useState, useEffect } from "react";
import { Upload, Download, AlertCircle, CheckCircle, Clock, XCircle, RefreshCw } from "lucide-react";
import { T, FS, SP, TIER_META } from "@/lib/tokens";
import {
  uploadBatchCSV,
  listBatches,
  getBatchDetail,
  downloadBatchReport,
  type BatchMetadata,
  type BatchDetail,
} from "@/lib/api";

interface PreviewRow {
  name: string;
  country: string;
  program?: string;
}

export function BatchImport() {
  const [tab, setTab] = useState<"upload" | "active" | "history">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [activeBatch, setActiveBatch] = useState<BatchDetail | null>(null);
  const [batches, setBatches] = useState<BatchMetadata[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [pollingInterval, setPollingInterval] = useState<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadBatches();
  }, []);

  useEffect(() => {
    if (activeBatch?.status === "processing" && !pollingInterval) {
      const interval = setInterval(() => {
        getBatchDetail(activeBatch.batch_id).then(setActiveBatch);
      }, 5000);
      setPollingInterval(interval);
    } else if (activeBatch?.status !== "processing" && pollingInterval) {
      clearInterval(pollingInterval);
      setPollingInterval(null);
    }
    return () => {
      if (pollingInterval) clearInterval(pollingInterval);
    };
  }, [activeBatch?.status, pollingInterval]);

  async function loadBatches() {
    try {
      const all = await listBatches();
      setBatches(all);
    } catch (err) {
      console.error("Failed to load batches:", err);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;

    setFile(f);
    setError("");
    setSuccess("");

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const lines = text.split("\n");
        const headerLine = lines[0];
        const headers = headerLine.split(",").map((h) => h.trim().toLowerCase());

        if (!headers.includes("name") || !headers.includes("country")) {
          setError("CSV must have 'name' and 'country' columns");
          setFile(null);
          return;
        }

        const rows: PreviewRow[] = [];
        for (let i = 1; i < Math.min(6, lines.length); i++) {
          const line = lines[i].trim();
          if (!line) continue;
          const parts = line.split(",").map((p) => p.trim());
          const nameIdx = headers.indexOf("name");
          const countryIdx = headers.indexOf("country");
          const programIdx = headers.indexOf("program");

          rows.push({
            name: parts[nameIdx] || "",
            country: parts[countryIdx] || "",
            program: programIdx >= 0 ? parts[programIdx] : "standard_industrial",
          });
        }
        setPreview(rows);
      } catch (err) {
        setError(`Failed to parse CSV: ${err}`);
        setFile(null);
      }
    };
    reader.readAsText(f);
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    (e.currentTarget as HTMLDivElement).style.background = T.hover;
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    (e.currentTarget as HTMLDivElement).style.background = "transparent";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    (e.currentTarget as HTMLDivElement).style.background = "transparent";
    const f = e.dataTransfer.files?.[0];
    if (f) {
      const input = document.getElementById("file-input") as HTMLInputElement;
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(f);
      input.files = dataTransfer.files;
      handleFileSelect({ target: input } as React.ChangeEvent<HTMLInputElement>);
    }
  }

  async function handleStartScreening() {
    if (!file) {
      setError("No file selected");
      return;
    }

    setUploading(true);
    setError("");
    setSuccess("");

    try {
      const result = await uploadBatchCSV(file);
      setSuccess(`Batch uploaded! Processing ${result.total_vendors} vendors...`);
      setFile(null);
      setPreview([]);
      setTab("active");
      setActiveBatch({
        batch_id: result.batch_id,
        filename: result.filename,
        uploaded_by: "",
        uploaded_by_email: "",
        status: result.status,
        total_vendors: result.total_vendors,
        processed: 0,
        completion_pct: 0,
        created_at: result.created_at,
        completed_at: null,
        items: [],
        summary: { completed: 0, tier_distribution: {}, total_findings: 0, avg_posterior: 0 },
      });
      loadBatches();
    } catch (err) {
      setError(`Upload failed: ${err}`);
    } finally {
      setUploading(false);
    }
  }

  function handleSelectBatch(batchId: string) {
    setSelectedBatchId(batchId);
    getBatchDetail(batchId).then(setActiveBatch);
    setTab("active");
  }

  function handleDownloadReport() {
    if (!activeBatch) return;
    downloadBatchReport(activeBatch.batch_id);
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle size={14} color={T.green} />;
      case "failed":
        return <XCircle size={14} color={T.red} />;
      case "processing":
        return <Clock size={14} color={T.amber} />;
      default:
        return <Clock size={14} color={T.muted} />;
    }
  };

  const tierColor = (tier: string) => {
    const meta = TIER_META[tier as keyof typeof TIER_META];
    return meta?.color || T.muted;
  };

  return (
    <div className="h-full flex flex-col gap-3" style={{ color: T.text }}>
      {/* Tabs */}
      <div className="flex gap-2 border-b" style={{ borderColor: T.border, paddingBottom: SP.sm }}>
        <button
          onClick={() => setTab("upload")}
          style={{
            fontSize: FS.sm,
            padding: `${SP.xs}px ${SP.md}px`,
            background: tab === "upload" ? T.accent + "22" : "transparent",
            color: tab === "upload" ? T.accent : T.muted,
            border: "none",
            cursor: "pointer",
            borderRadius: 4,
          }}
        >
          <Upload size={12} style={{ marginRight: 4, display: "inline" }} />
          Upload CSV
        </button>
        <button
          onClick={() => setTab("active")}
          style={{
            fontSize: FS.sm,
            padding: `${SP.xs}px ${SP.md}px`,
            background: tab === "active" ? T.accent + "22" : "transparent",
            color: tab === "active" ? T.accent : T.muted,
            border: "none",
            cursor: "pointer",
            borderRadius: 4,
          }}
        >
          <RefreshCw size={12} style={{ marginRight: 4, display: "inline" }} />
          Processing
        </button>
        <button
          onClick={() => setTab("history")}
          style={{
            fontSize: FS.sm,
            padding: `${SP.xs}px ${SP.md}px`,
            background: tab === "history" ? T.accent + "22" : "transparent",
            color: tab === "history" ? T.accent : T.muted,
            border: "none",
            cursor: "pointer",
            borderRadius: 4,
          }}
        >
          <Clock size={12} style={{ marginRight: 4, display: "inline" }} />
          History
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {tab === "upload" && (
          <div className="space-y-4">
            {/* Upload Area */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              style={{
                border: `2px dashed ${T.border}`,
                borderRadius: 8,
                padding: SP.xl,
                textAlign: "center",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = T.accent)}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = T.border)}
            >
              <Upload size={32} color={T.accent} style={{ margin: "0 auto" }} />
              <div style={{ fontSize: FS.md, fontWeight: 600, marginTop: SP.md }}>
                Drag CSV here or click to browse
              </div>
              <div style={{ fontSize: FS.sm, color: T.muted, marginTop: SP.sm }}>
                Required columns: name, country
              </div>
              <input
                id="file-input"
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                style={{ display: "none" }}
              />
              <button
                onClick={() => document.getElementById("file-input")?.click()}
                style={{
                  marginTop: SP.md,
                  padding: `${SP.xs}px ${SP.md}px`,
                  background: T.accent,
                  color: "#fff",
                  border: "none",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: FS.sm,
                }}
              >
                Browse Files
              </button>
            </div>

            {/* Error/Success Messages */}
            {error && (
              <div
                style={{
                  background: T.redBg,
                  border: `1px solid ${T.red}`,
                  borderRadius: 6,
                  padding: SP.md,
                  display: "flex",
                  gap: SP.md,
                  color: T.red,
                }}
              >
                <AlertCircle size={16} style={{ flexShrink: 0 }} />
                <div style={{ fontSize: FS.sm }}>{error}</div>
              </div>
            )}
            {success && (
              <div
                style={{
                  background: T.greenBg,
                  border: `1px solid ${T.green}`,
                  borderRadius: 6,
                  padding: SP.md,
                  display: "flex",
                  gap: SP.md,
                  color: T.green,
                }}
              >
                <CheckCircle size={16} style={{ flexShrink: 0 }} />
                <div style={{ fontSize: FS.sm }}>{success}</div>
              </div>
            )}

            {/* Preview */}
            {preview.length > 0 && (
              <div>
                <div style={{ fontSize: FS.md, fontWeight: 600, marginBottom: SP.md }}>
                  Preview ({preview.length} rows shown)
                </div>
                <div style={{ overflowX: "auto", borderRadius: 6, border: `1px solid ${T.border}` }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: FS.sm,
                    }}
                  >
                    <thead>
                      <tr style={{ background: T.surface, borderBottom: `1px solid ${T.border}` }}>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Name</th>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Country</th>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Program</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.map((row, i) => (
                        <tr
                          key={i}
                          style={{
                            borderBottom: `1px solid ${T.border}`,
                            background: i % 2 === 0 ? "transparent" : T.hover,
                          }}
                        >
                          <td style={{ padding: SP.md }}>{row.name}</td>
                          <td style={{ padding: SP.md }}>{row.country}</td>
                          <td style={{ padding: SP.md, color: T.muted }}>{row.program || "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Start Button */}
                <button
                  onClick={handleStartScreening}
                  disabled={uploading}
                  style={{
                    marginTop: SP.lg,
                    padding: `${SP.sm}px ${SP.lg}px`,
                    background: uploading ? T.muted : T.accent,
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: uploading ? "not-allowed" : "pointer",
                    fontSize: FS.md,
                    fontWeight: 600,
                    opacity: uploading ? 0.5 : 1,
                  }}
                >
                  {uploading ? "Uploading..." : "Start Screening"}
                </button>
              </div>
            )}
          </div>
        )}

        {tab === "active" && activeBatch && (
          <div className="space-y-4">
            <div
              style={{
                background: T.surface,
                border: `1px solid ${T.border}`,
                borderRadius: 8,
                padding: SP.lg,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: SP.md }}>
                <div>
                  <div style={{ fontSize: FS.md, fontWeight: 600, marginBottom: SP.xs }}>
                    {activeBatch.filename}
                  </div>
                  <div style={{ fontSize: FS.sm, color: T.muted }}>
                    {activeBatch.processed} of {activeBatch.total_vendors} vendors processed
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: SP.sm,
                    padding: `${SP.xs}px ${SP.md}px`,
                    background: T.hover,
                    borderRadius: 4,
                  }}
                >
                  {statusIcon(activeBatch.status)}
                  <span style={{ fontSize: FS.sm, fontWeight: 600, textTransform: "uppercase" }}>
                    {activeBatch.status}
                  </span>
                </div>
              </div>

              {/* Progress Bar */}
              <div style={{ marginBottom: SP.lg }}>
                <div
                  style={{
                    height: 8,
                    background: T.border,
                    borderRadius: 4,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      background: T.accent,
                      width: `${activeBatch.completion_pct}%`,
                      transition: "width 0.3s ease",
                    }}
                  />
                </div>
                <div style={{ fontSize: FS.xs, color: T.muted, marginTop: SP.xs }}>
                  {activeBatch.completion_pct}% complete
                </div>
              </div>

              {/* Summary Stats */}
              {activeBatch.summary && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                    gap: SP.md,
                    marginBottom: SP.lg,
                  }}
                >
                  <div style={{ background: T.bg, padding: SP.md, borderRadius: 6 }}>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Completed</div>
                    <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.green }}>
                      {activeBatch.summary.completed}
                    </div>
                  </div>
                  <div style={{ background: T.bg, padding: SP.md, borderRadius: 6 }}>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Total Findings</div>
                    <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.orange }}>
                      {activeBatch.summary.total_findings}
                    </div>
                  </div>
                  <div style={{ background: T.bg, padding: SP.md, borderRadius: 6 }}>
                    <div style={{ fontSize: FS.xs, color: T.muted }}>Avg Posterior</div>
                    <div style={{ fontSize: FS.lg, fontWeight: 600, color: T.amber }}>
                      {(activeBatch.summary.avg_posterior * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
              )}

              {/* Tier Distribution */}
              {Object.keys(activeBatch.summary.tier_distribution).length > 0 && (
                <div style={{ marginBottom: SP.lg }}>
                  <div style={{ fontSize: FS.sm, fontWeight: 600, marginBottom: SP.md }}>Tier Distribution</div>
                  <div style={{ display: "flex", gap: SP.md, flexWrap: "wrap" }}>
                    {Object.entries(activeBatch.summary.tier_distribution).map(([tier, count]) => {
                      const meta = TIER_META[tier as keyof typeof TIER_META];
                      return (
                        <div
                          key={tier}
                          style={{
                            padding: `${SP.xs}px ${SP.md}px`,
                            background: meta?.bg || T.surface,
                            color: meta?.color || T.text,
                            borderRadius: 4,
                            fontSize: FS.sm,
                            fontWeight: 600,
                          }}
                        >
                          {meta?.label || tier}: {count}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Download Button */}
              {activeBatch.status === "completed" && (
                <button
                  onClick={handleDownloadReport}
                  style={{
                    padding: `${SP.xs}px ${SP.lg}px`,
                    background: T.accent,
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                    fontSize: FS.sm,
                    display: "flex",
                    alignItems: "center",
                    gap: SP.sm,
                  }}
                >
                  <Download size={14} />
                  Download Report
                </button>
              )}
            </div>

            {/* Items List */}
            {activeBatch.items.length > 0 && (
              <div>
                <div style={{ fontSize: FS.md, fontWeight: 600, marginBottom: SP.md }}>Results</div>
                <div style={{ overflowX: "auto", borderRadius: 6, border: `1px solid ${T.border}` }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: FS.xs,
                    }}
                  >
                    <thead>
                      <tr style={{ background: T.surface, borderBottom: `1px solid ${T.border}` }}>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Vendor</th>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Country</th>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Status</th>
                        <th style={{ padding: SP.md, textAlign: "left", fontWeight: 600 }}>Tier</th>
                        <th style={{ padding: SP.md, textAlign: "right", fontWeight: 600 }}>Posterior</th>
                        <th style={{ padding: SP.md, textAlign: "right", fontWeight: 600 }}>Findings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeBatch.items.map((item, i) => (
                        <tr
                          key={i}
                          style={{
                            borderBottom: `1px solid ${T.border}`,
                            background: i % 2 === 0 ? "transparent" : T.hover,
                          }}
                        >
                          <td style={{ padding: SP.md }}>{item.vendor_name}</td>
                          <td style={{ padding: SP.md }}>{item.country}</td>
                          <td style={{ padding: SP.md, display: "flex", alignItems: "center", gap: SP.xs }}>
                            {statusIcon(item.status)}
                            {item.status}
                          </td>
                          <td style={{ padding: SP.md, color: tierColor(item.tier || "") }}>
                            {item.tier || "–"}
                          </td>
                          <td style={{ padding: SP.md, textAlign: "right", color: T.amber }}>
                            {item.posterior ? (item.posterior * 100).toFixed(0) + "%" : "–"}
                          </td>
                          <td style={{ padding: SP.md, textAlign: "right" }}>
                            {item.findings_count ?? "–"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "history" && (
          <div className="space-y-3">
            {batches.length === 0 ? (
              <div style={{ color: T.muted, fontSize: FS.sm, textAlign: "center", paddingTop: SP.xl }}>
                No batches found
              </div>
            ) : (
              batches.map((batch) => (
                <button
                  key={batch.id}
                  onClick={() => handleSelectBatch(batch.id)}
                  style={{
                    width: "100%",
                    padding: SP.lg,
                    background: selectedBatchId === batch.id ? T.accent + "22" : T.surface,
                    border: `1px solid ${selectedBatchId === batch.id ? T.accent : T.border}`,
                    borderRadius: 8,
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background =
                      selectedBatchId === batch.id ? T.accent + "22" : T.hover)
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background =
                      selectedBatchId === batch.id ? T.accent + "22" : T.surface)
                  }
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                    <div>
                      <div style={{ fontSize: FS.sm, fontWeight: 600, marginBottom: SP.xs }}>
                        {batch.filename}
                      </div>
                      <div style={{ fontSize: FS.xs, color: T.muted }}>
                        {batch.total_vendors} vendors • {batch.processed} processed • {batch.completion_pct}%
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: SP.sm }}>
                      {statusIcon(batch.status)}
                      <span style={{ fontSize: FS.xs, fontWeight: 600, textTransform: "uppercase" }}>
                        {batch.status}
                      </span>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
