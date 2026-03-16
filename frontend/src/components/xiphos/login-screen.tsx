import { useState } from "react";
import { Shield, Lock, AlertTriangle, UserPlus } from "lucide-react";
import { T } from "@/lib/tokens";
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
      className="h-screen flex items-center justify-center"
      style={{ background: T.bg }}
    >
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div
            className="flex items-center justify-center rounded-lg mb-3"
            style={{
              width: 48,
              height: 48,
              background: T.accent + "18",
            }}
          >
            <Shield size={26} color={T.accent} />
          </div>
          <span
            className="font-mono font-bold"
            style={{ fontSize: 18, letterSpacing: "0.15em", color: T.text }}
          >
            XIPHOS
          </span>
          <span style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>
            Intelligence-Grade Vendor Assurance
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
            <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>
              {mode === "setup" ? "Create Admin Account" : "Sign In"}
            </span>
          </div>

          {mode === "setup" && (
            <div
              className="rounded p-3 mb-4 flex items-start gap-2"
              style={{ background: T.amberBg, fontSize: 11, color: T.amber }}
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
              style={{ background: T.redBg, fontSize: 11, color: T.red }}
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            {mode === "setup" && (
              <div>
                <label
                  style={{ fontSize: 11, color: T.muted, display: "block", marginBottom: 4 }}
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
                    fontSize: 13,
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    color: T.text,
                  }}
                />
              </div>
            )}

            <div>
              <label
                style={{ fontSize: 11, color: T.muted, display: "block", marginBottom: 4 }}
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
                  fontSize: 13,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              />
            </div>

            <div>
              <label
                style={{ fontSize: 11, color: T.muted, display: "block", marginBottom: 4 }}
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
                  fontSize: 13,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  color: T.text,
                }}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="rounded font-medium cursor-pointer"
              style={{
                padding: "9px 0",
                fontSize: 13,
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
                fontSize: 11,
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
                fontSize: 11,
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

        {/* Classification banner */}
        <div
          className="text-center mt-4 font-mono"
          style={{ fontSize: 9, color: T.muted }}
        >
          XIPHOS v2.6 &mdash; UNCLASSIFIED // FOR OFFICIAL USE ONLY
        </div>
      </div>
    </div>
  );
}
