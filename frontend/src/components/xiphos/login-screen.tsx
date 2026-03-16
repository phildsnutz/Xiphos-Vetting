import { useState } from "react";
import { Shield, Lock, AlertTriangle, UserPlus } from "lucide-react";
import { T, FS } from "@/lib/tokens";
import { login, setup } from "@/lib/auth";
import type { AuthUser } from "@/lib/auth";

interface LoginScreenProps {
  onLogin: (user: AuthUser) => void;
  needsSetup: boolean;
}

export function LoginScreen({ onLogin, needsSetup }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"login" | "setup">(needsSetup ? "setup" : "login");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === "setup") {
        if (!name.trim()) {
          setError("Name is required for initial setup");
          setLoading(false);
          return;
        }
        const result = await setup(email, password, name);
        onLogin(result.user);
      } else {
        const result = await login(email, password);
        onLogin(result.user);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="h-screen flex flex-col items-center justify-center"
      style={{ background: T.bg }}
    >
      {/* CUI Banner - top */}
      <div
        className="fixed top-0 left-0 right-0 text-center py-1.5"
        style={{ background: T.hardStopBg, borderBottom: `2px solid ${T.hardStopBorder}` }}
      >
        <span className="font-bold tracking-wider" style={{ fontSize: FS.xs, color: "#ffffff" }}>
          CUI // CONTROLLED UNCLASSIFIED INFORMATION
        </span>
      </div>

      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div
            className="flex items-center justify-center rounded-lg mb-4"
            style={{
              width: 56,
              height: 56,
              background: T.accent + "18",
              border: `1px solid ${T.accent}33`,
            }}
          >
            <Shield size={30} color={T.accent} />
          </div>
          <span
            className="font-bold tracking-widest"
            style={{ fontSize: 22, letterSpacing: "0.2em", color: T.text }}
          >
            XIPHOS
          </span>
          <span style={{ fontSize: FS.sm, color: T.dim, marginTop: 6, textAlign: "center" }}>
            Defense Supply Chain Intelligence Platform
          </span>
          <span style={{ fontSize: FS.xs, color: T.muted, marginTop: 2 }}>
            Vendor Vetting &amp; Continuous Monitoring
          </span>
        </div>

        {/* Card */}
        <div
          className="rounded-lg p-6"
          style={{
            background: T.surface,
            border: `1px solid ${T.border}`,
          }}
        >
          <div className="flex items-center gap-2 mb-5">
            {mode === "setup" ? (
              <UserPlus size={14} color={T.accent} />
            ) : (
              <Lock size={14} color={T.accent} />
            )}
            <span style={{ fontSize: FS.md, fontWeight: 600, color: T.text }}>
              {mode === "setup" ? "Create Admin Account" : "Secure Sign In"}
            </span>
          </div>

          {mode === "setup" && (
            <div
              className="rounded p-3 mb-4 flex items-start gap-2"
              style={{ background: T.amberBg, fontSize: FS.xs, color: T.amber }}
            >
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                No users exist yet. Create the initial administrator account.
                This can only be done once.
              </span>
            </div>
          )}

          {error && (
            <div
              className="rounded p-3 mb-4"
              style={{ background: T.redBg, fontSize: FS.xs, color: T.red }}
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            {mode === "setup" && (
              <div>
                <label
                  style={{ fontSize: FS.xs, color: T.muted, display: "block", marginBottom: 4 }}
                >
                  Full Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Administrator"
                  required
                  className="w-full rounded outline-none"
                  style={{
                    padding: "8px 12px",
                    fontSize: FS.base,
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                  }}
                />
              </div>
            )}

            <div>
              <label
                style={{ fontSize: FS.xs, color: T.muted, display: "block", marginBottom: 4 }}
              >
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="analyst@yourorg.com"
                required
                autoComplete="email"
                className="w-full rounded outline-none"
                style={{
                  padding: "8px 12px",
                  fontSize: FS.base,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              />
            </div>

            <div>
              <label
                style={{ fontSize: FS.xs, color: T.muted, display: "block", marginBottom: 4 }}
              >
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                required
                minLength={8}
                autoComplete={mode === "setup" ? "new-password" : "current-password"}
                className="w-full rounded outline-none"
                style={{
                  padding: "8px 12px",
                  fontSize: FS.base,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="rounded font-semibold cursor-pointer"
              style={{
                padding: "10px 0",
                fontSize: FS.base,
                background: loading ? T.muted : T.accent,
                color: "#fff",
                border: "none",
                marginTop: 4,
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading
                ? "Authenticating..."
                : mode === "setup"
                  ? "Create Admin & Sign In"
                  : "Sign In"}
            </button>
          </form>

          {/* Toggle between login and setup */}
          {!needsSetup && mode === "login" && (
            <button
              onClick={() => setMode("setup")}
              className="w-full mt-3 cursor-pointer"
              style={{
                fontSize: FS.xs,
                color: T.muted,
                background: "none",
                border: "none",
                textDecoration: "underline",
                textUnderlineOffset: 2,
              }}
            >
              First time? Set up admin account
            </button>
          )}
          {mode === "setup" && !needsSetup && (
            <button
              onClick={() => setMode("login")}
              className="w-full mt-3 cursor-pointer"
              style={{
                fontSize: FS.xs,
                color: T.muted,
                background: "none",
                border: "none",
                textDecoration: "underline",
                textUnderlineOffset: 2,
              }}
            >
              Already have an account? Sign in
            </button>
          )}
        </div>

        {/* System info */}
        <div
          className="text-center mt-4"
          style={{ fontSize: FS.xs, color: T.muted }}
        >
          XIPHOS v3.1 // System of Record // Defense Acquisition
        </div>
      </div>

      {/* CUI Banner - bottom */}
      <div
        className="fixed bottom-0 left-0 right-0 text-center py-1.5"
        style={{ background: T.hardStopBg, borderTop: `2px solid ${T.hardStopBorder}` }}
      >
        <span className="font-bold tracking-wider" style={{ fontSize: FS.xs, color: "#ffffff" }}>
          CUI // CONTROLLED UNCLASSIFIED INFORMATION
        </span>
      </div>
    </div>
  );
}
