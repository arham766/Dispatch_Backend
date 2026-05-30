/**
 * Shotgun — Auth React context + hook.
 *
 * Wraps the app: subscribes to Firebase auth state, exposes the current
 * user, and provides a fetch helper that auto-attaches the ID token.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { User } from "firebase/auth";
import {
  getIdToken,
  onAuthStateChanged,
  signInWithGoogle as fbSignInWithGoogle,
  signInWithGithub as fbSignInWithGithub,
  signOut as fbSignOut,
} from "./firebase";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signInWithGithub: () => Promise<void>;
  signOut: () => Promise<void>;
  authedFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged((u) => {
      setUser(u);
      setLoading(false);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async () => {
    await fbSignInWithGoogle();
  }, []);

  const signInWithGithub = useCallback(async () => {
    await fbSignInWithGithub();
  }, []);

  const signOut = useCallback(async () => {
    await fbSignOut();
  }, []);

  const authedFetch = useCallback(
    async (path: string, init: RequestInit = {}): Promise<Response> => {
      const API = process.env.NEXT_PUBLIC_API || "http://localhost:8000";
      const url = path.startsWith("http") ? path : `${API}${path}`;
      const token = await getIdToken();
      const headers = new Headers(init.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      if (!headers.has("Content-Type") && init.body) {
        headers.set("Content-Type", "application/json");
      }
      return fetch(url, { ...init, headers });
    },
    []
  );

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signInWithGithub, signOut, authedFetch }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
