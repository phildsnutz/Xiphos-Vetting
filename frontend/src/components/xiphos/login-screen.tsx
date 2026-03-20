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
      className="h-screen flex items-center justify-center px-4"
      style={{
        background: `radial-gradient(circle at top, ${T.accent}12, transparent 34%), ${T.bg}`,
      }}
    >
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <span style={{ fontSize: 11, color: T.muted, letterSpacing: "0.12em", fontWeight: 600, marginBottom: 10 }}>
            Xiphos
          </span>
          <div
            className="flex items-center justify-center rounded-lg mb-4"
            style={{
              width: 52,
              height: 52,
              background: T.accent + "18",
              border: `1px solid ${T.accent}33`,
            }}
          >
            <Shield size={26} color={T.accent} />
          </div>
          <span style={{ fontSize: 26, color: T.text, fontWeight: 700 }}>
            Helios
          </span>
          <span style={{ fontSize: FS.base, color: T.dim, marginTop: 6, textAlign: "center", lineHeight: 1.5 }}>
            Vendor intelligence and assurance
          </span>
        </div>

        <div
          className="rounded-lg p-6"
          style={{
            background: T.surface,
            border: `1px solid ${T.border}`,
            boxShadow: "0 18px 48px rgba(0,0,0,0.28)",
          }}
        >
          <div className="flex items-center gap-2 mb-5">
            {mode === "setup" ? (
              <UserPlus size={14} color={T.accent} />
            ) : (
              <Lock size={14} color={T.accent} />
            )}
            <span style={{ fontSize: FS.md, fontWeight: 600, color: T.text }}>
              {mode === "setup" ? "Set up workspace" : "Sign in"}
            </span>
          </div>

          {mode === "setup" && (
            <div
              className="rounded p-3 mb-4 flex items-start gap-2"
              style={{ background: T.amberBg, fontSize: FS.sm, color: T.amber, border: `1px solid ${T.amber}33` }}
            >
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                No users exist yet. Create the initial administrator account for this workspace.
              </span>
            </div>
          )}

          {error && (
            <div
              className="rounded p-3 mb-4"
              style={{ background: T.redBg, fontSize: FS.sm, color: T.red }}
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            {mode === "setup" && (
              <div>
                <label
                  style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 4 }}
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
                style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 4 }}
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
                style={{ fontSize: FS.sm, color: T.muted, display: "block", marginBottom: 4 }}
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
                padding: "11px 0",
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
                  ? "Create admin and continue"
                  : "Sign In"}
            </button>
          </form>

          {!needsSetup && mode === "login" && (
            <button
              onClick={() => setMode("setup")}
              className="w-full mt-3 cursor-pointer"
              style={{
                fontSize: FS.sm,
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
                fontSize: FS.sm,
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

        <div
          className="text-center mt-4"
          style={{ fontSize: FS.sm, color: T.muted, lineHeight: 1.5 }}
        >
          Helios v5.2
          <br />
          For authorized workspace use only
          <br />
          <span style={{ color: T.dim }}>Proprietary information. Unauthorized disclosure prohibited.</span>
        </div>
      </div>
    </div>
  );
}
