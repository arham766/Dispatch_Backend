/**
 * Dispatch — Auth React context + authedFetch helper.
 *
 * Subscribes to Firebase auth state, exposes the current user, and
 * wraps fetch with an Authorization: Bearer <Firebase ID token> header
 * so any backend route that uses `Depends(require_user)` Just Works.
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
  signInWithGithub as fbSignInWithGithub,
  signInWithGoogle as fbSignInWithGoogle,
  signOut as fbSignOut,
} from "./firebase";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  signInWithGithub: () => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  authedFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const API_BASE =
  process.env.NEXT_PUBLIC_API || "http://localhost:8000";

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

  const signInWithGithub = useCallback(async () => {
    await fbSignInWithGithub();
  }, []);

  const signInWithGoogle = useCallback(async () => {
    await fbSignInWithGoogle();
  }, []);

  const signOut = useCallback(async () => {
    await fbSignOut();
  }, []);

  const authedFetch = useCallback(
    async (path: string, init: RequestInit = {}): Promise<Response> => {
      const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
      const token = await getIdToken();
      const headers = new Headers(init.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      if (!headers.has("Content-Type") && init.body) {
        headers.set("Content-Type", "application/json");
      }
      return fetch(url, { ...init, headers });
    },
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signInWithGithub,
        signInWithGoogle,
        signOut,
        authedFetch,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
