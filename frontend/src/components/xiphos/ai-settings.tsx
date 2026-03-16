import { useState, useEffect } from "react";
import { T } from "@/lib/tokens";
import { Brain, Check, Trash2, AlertTriangle, Building2 } from "lucide-react";
import {
  fetchAIProviders, fetchAIConfig, saveAIConfig, deleteAIConfig, saveOrgAIConfig,
} from "@/lib/api";
import type { AIProvider, AIConfig } from "@/lib/api";
import type { AuthUser } from "@/lib/auth";

interface AISettingsProps {
  currentUser: AuthUser;
}

export function AISettings({ currentUser }: AISettingsProps) {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [config, setConfig] = useState<AIConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [selectedProvider, setSelectedProvider] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [isOrgDefault, setIsOrgDefault] = useState(false);

  const isAdmin = currentUser.role === "admin";

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [provs, cfg] = await Promise.all([
        fetchAIProviders(),
        fetchAIConfig(),
      ]);
      setProviders(provs);
      setConfig(cfg);
      if (cfg.configured && cfg.provider) {
        setSelectedProvider(cfg.provider);
        const prov = provs.find((p) => p.name === cfg.provider);
        setSelectedModel(cfg.model || prov?.default_model || "");
      } else if (provs.length > 0) {
        setSelectedProvider(provs[0].name);
        setSelectedModel(provs[0].default_model);
      }
    } catch {
      setError("Could not load AI settings. The AI module may not be available on the server.");
    } finally {
      setLoading(false);
    }
  }

  function handleProviderChange(name: string) {
    setSelectedProvider(name);
    const prov = providers.find((p) => p.name === name);
    if (prov) setSelectedModel(prov.default_model);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey && !config?.configured) {
      setError("API key is required");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const keyToSave = apiKey || "UNCHANGED"; // Backend won't accept empty
      if (isOrgDefault && isAdmin) {
        await saveOrgAIConfig(selectedProvider, selectedModel, keyToSave);
        setSuccess(`Organization default set to ${selectedProvider}/${selectedModel}`);
      } else {
        await saveAIConfig(selectedProvider, selectedModel, keyToSave);
        setSuccess(`Saved ${selectedProvider}/${selectedModel} configuration`);
      }
      setApiKey("");
      // Reload config
      const cfg = await fetchAIConfig();
      setConfig(cfg);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setSaving(true);
    setError(null);
    try {
      await deleteAIConfig();
      setConfig({ configured: false });
      setApiKey("");
      setSuccess("AI configuration removed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="p-6 text-center" style={{ fontSize: 12, color: T.muted }}>
        Loading AI settings...
      </div>
    );
  }

  const currentProv = providers.find((p) => p.name === selectedProvider);

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Brain size={16} color={T.accent} />
        <span style={{ fontSize: 14, fontWeight: 600, color: T.text }}>
          AI Provider Settings
        </span>
      </div>

      <div style={{ fontSize: 12, color: T.dim, lineHeight: 1.5 }}>
        Configure your AI provider to enable intelligent risk narratives,
        executive summaries, and actionable recommendations powered by LLM analysis.
        Your API key is encrypted at rest using the server's secret key.
      </div>

      {/* Current status */}
      {config?.configured && (
        <div
          className="flex items-center justify-between rounded-lg p-3"
          style={{ background: T.greenBg, border: `1px solid ${T.green}33` }}
        >
          <div className="flex items-center gap-2">
            <Check size={14} color={T.green} />
            <span style={{ fontSize: 12, color: T.green }}>
              Active: <strong>{config.provider}</strong> / {config.model}
            </span>
            <span className="font-mono" style={{ fontSize: 10, color: T.green }}>
              (key: {config.api_key_hint})
            </span>
          </div>
          <button
            onClick={handleDelete}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded cursor-pointer"
            style={{
              padding: "4px 8px", fontSize: 10,
              background: "transparent", border: `1px solid ${T.red}44`, color: T.red,
            }}
          >
            <Trash2 size={10} />
            Remove
          </button>
        </div>
      )}

      {/* Status messages */}
      {success && (
        <div className="rounded p-2.5" style={{ background: T.greenBg, fontSize: 11, color: T.green }}>
          {success}
        </div>
      )}
      {error && (
        <div className="rounded p-2.5 flex items-center gap-2" style={{ background: T.redBg, fontSize: 11, color: T.red }}>
          <AlertTriangle size={12} />
          {error}
        </div>
      )}

      {/* Provider form */}
      <form onSubmit={handleSave} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          {/* Provider selector */}
          <div>
            <label style={{ fontSize: 10, color: T.muted, display: "block", marginBottom: 3 }}>
              Provider
            </label>
            <select
              value={selectedProvider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full rounded outline-none cursor-pointer"
              style={{
                padding: "8px 10px", fontSize: 12,
                background: T.bg, border: `1px solid ${T.border}`, color: T.text,
              }}
            >
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>

          {/* Model selector */}
          <div>
            <label style={{ fontSize: 10, color: T.muted, display: "block", marginBottom: 3 }}>
              Model
            </label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="w-full rounded outline-none cursor-pointer"
              style={{
                padding: "8px 10px", fontSize: 12,
                background: T.bg, border: `1px solid ${T.border}`, color: T.text,
              }}
            >
              {currentProv?.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>

        {/* API Key */}
        <div>
          <label style={{ fontSize: 10, color: T.muted, display: "block", marginBottom: 3 }}>
            API Key {config?.configured && "(leave blank to keep existing)"}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={config?.configured ? "Existing key on file" : "sk-... or your provider key"}
            required={!config?.configured}
            autoComplete="off"
            className="w-full rounded outline-none"
            style={{
              padding: "8px 10px", fontSize: 12,
              background: T.bg, border: `1px solid ${T.border}`, color: T.text,
            }}
          />
        </div>

        {/* Org default toggle (admin only) */}
        {isAdmin && (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isOrgDefault}
              onChange={(e) => setIsOrgDefault(e.target.checked)}
              style={{ accentColor: T.accent }}
            />
            <Building2 size={12} color={T.muted} />
            <span style={{ fontSize: 11, color: T.dim }}>
              Set as organization default (applies to all users who haven't configured their own)
            </span>
          </label>
        )}

        <button
          type="submit"
          disabled={saving}
          className="self-start rounded px-4 py-2 cursor-pointer"
          style={{
            fontSize: 12,
            background: saving ? T.muted : T.accent,
            color: "#fff",
            border: "none",
            opacity: saving ? 0.7 : 1,
          }}
        >
          {saving ? "Saving..." : "Save Configuration"}
        </button>
      </form>

      {/* Provider info cards */}
      <div style={{ marginTop: 8 }}>
        <div className="font-semibold uppercase tracking-wider mb-2" style={{ fontSize: 10, color: T.muted }}>
          Available Providers
        </div>
        <div className="grid grid-cols-3 gap-2">
          {providers.map((p) => (
            <div
              key={p.name}
              className="rounded-lg p-3 cursor-pointer"
              onClick={() => handleProviderChange(p.name)}
              style={{
                background: selectedProvider === p.name ? T.accent + "12" : T.raised,
                border: `1px solid ${selectedProvider === p.name ? T.accent + "44" : T.border}`,
              }}
            >
              <div className="font-medium" style={{ fontSize: 12, color: T.text }}>
                {p.display_name}
              </div>
              <div className="font-mono" style={{ fontSize: 9, color: T.muted, marginTop: 4 }}>
                {p.models.join(", ")}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
