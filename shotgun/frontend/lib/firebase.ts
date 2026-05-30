/**
 * Shotgun — Firebase web client (browser side).
 *
 * Initializes the Firebase app from NEXT_PUBLIC_FIREBASE_* env vars and
 * exposes:
 *   - `auth`             — the Firebase Auth instance
 *   - `signInWithGoogle` — popup-based sign-in
 *   - `signOut`          — wipe session
 *   - `getIdToken()`     — fetch a fresh ID token to send to the backend
 *
 * Server-side rendering: every import is guarded with `typeof window` so
 * the bundle is safe to import from RSC modules.
 */

import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  GithubAuthProvider,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as fbSignOut,
  onAuthStateChanged as fbOnAuthStateChanged,
  type Auth,
  type User,
  type UserCredential,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  measurementId: process.env.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID,
};

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;

function getFirebaseApp(): FirebaseApp {
  if (_app) return _app;
  _app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
  return _app;
}

export function getFirebaseAuth(): Auth {
  if (_auth) return _auth;
  _auth = getAuth(getFirebaseApp());
  return _auth;
}

export async function signInWithGoogle(): Promise<User> {
  const auth = getFirebaseAuth();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const result = await signInWithPopup(auth, provider);
  return result.user;
}

/**
 * Sign in with GitHub via Firebase. Requests the `repo` scope so the
 * resulting OAuth access token can list + read + write the user's
 * repositories. The token is captured at sign-in time and persisted
 * to sessionStorage; useful for one-shot listing without going through
 * the full GitHub App install flow.
 *
 * For org installations and webhooks we still want the App — but for
 * individual users importing a single repo, this is one click.
 */
export async function signInWithGithub(): Promise<{
  user: User;
  accessToken: string | null;
}> {
  const auth = getFirebaseAuth();
  const provider = new GithubAuthProvider();
  provider.addScope("repo");           // full read/write to public + private
  provider.addScope("workflow");       // commit .github/workflows/*
  provider.addScope("read:user");
  provider.setCustomParameters({ allow_signup: "true" });

  const result: UserCredential = await signInWithPopup(auth, provider);
  const credential = GithubAuthProvider.credentialFromResult(result);
  const accessToken = credential?.accessToken ?? null;

  // Keep the token for the rest of this browser session so /onboarding
  // and the dashboard can hit GitHub directly without re-prompting.
  if (typeof window !== "undefined" && accessToken) {
    sessionStorage.setItem("gh_access_token", accessToken);
  }

  return { user: result.user, accessToken };
}

/** Fetch the GitHub access token captured at sign-in (if any). */
export function getGithubAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("gh_access_token");
}

export async function signOut(): Promise<void> {
  await fbSignOut(getFirebaseAuth());
}

export function onAuthStateChanged(cb: (user: User | null) => void): () => void {
  return fbOnAuthStateChanged(getFirebaseAuth(), cb);
}

/** Get a fresh ID token to send as `Authorization: Bearer <token>`. */
export async function getIdToken(forceRefresh = false): Promise<string | null> {
  const user = getFirebaseAuth().currentUser;
  if (!user) return null;
  return user.getIdToken(forceRefresh);
}
