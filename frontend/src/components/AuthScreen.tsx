import React, { useState } from "react";
import { loginUser, registerUser } from "../api";

interface AuthScreenProps {
  onAuthSuccess: (session: { token: string; user: { id: string; email: string; display_name?: string | null } }) => void;
}

const AuthScreen: React.FC<AuthScreenProps> = ({ onAuthSuccess }) => {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      if (mode === "login") {
        const session = await loginUser({ email, password });
        onAuthSuccess(session);
      } else {
        const session = await registerUser({ email, password, display_name: displayName || null });
        onAuthSuccess(session);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-container">
        <img src="/logo.png" alt="Urban Sentinel" className="auth-logo" />
        <h2 className="auth-app-title">LiGuard DT</h2>
        <div className="auth-panel">
          <div className="auth-header">
            <h1>{mode === "login" ? "Welcome back" : "Create your account"}</h1>
            <p className="auth-subtitle">
              {mode === "login"
                ? "Sign in to manage your graphs across devices."
                : "Set up your workspace and start building graphs."}
            </p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {mode === "register" && (
              <label className="auth-field">
                <span>Display name</span>
                <input
                  type="text"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Optional"
                  autoComplete="name"
                />
              </label>
            )}

            <label className="auth-field">
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                required
              />
            </label>

            <label className="auth-field">
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Minimum 8 characters"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={8}
              />
            </label>

            {error && <div className="auth-error">{error}</div>}

            <button type="submit" className="auth-submit" disabled={isSubmitting}>
              {isSubmitting ? "Working..." : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <div className="auth-footer">
            <span>
              {mode === "login" ? "New here?" : "Already have an account?"}
            </span>
            <button
              type="button"
              className="auth-toggle"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "Create one" : "Sign in"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AuthScreen;
