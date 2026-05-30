/**
 * Dispatch — Firebase web SDK init + sign-in helpers.
 *
 * Reads NEXT_PUBLIC_FIREBASE_* env at build time. All values are public
 * by design — security lives in Firebase rules + backend token verify.
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

export async function signInWithGithub(): Promise<{
  user: User;
  accessToken: string | null;
}> {
  const auth = getFirebaseAuth();
  const provider = new GithubAuthProvider();
  provider.addScope("repo");
  provider.addScope("workflow");
  provider.addScope("read:user");
  provider.setCustomParameters({ allow_signup: "true" });

  const result: UserCredential = await signInWithPopup(auth, provider);
  const credential = GithubAuthProvider.credentialFromResult(result);
  const accessToken = credential?.accessToken ?? null;

  if (typeof window !== "undefined" && accessToken) {
    sessionStorage.setItem("gh_access_token", accessToken);
  }
  return { user: result.user, accessToken };
}

export async function signInWithGoogle(): Promise<User> {
  const auth = getFirebaseAuth();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const result = await signInWithPopup(auth, provider);
  return result.user;
}

export async function signOut(): Promise<void> {
  await fbSignOut(getFirebaseAuth());
}

export function onAuthStateChanged(cb: (user: User | null) => void): () => void {
  return fbOnAuthStateChanged(getFirebaseAuth(), cb);
}

export async function getIdToken(forceRefresh = false): Promise<string | null> {
  const user = getFirebaseAuth().currentUser;
  if (!user) return null;
  return user.getIdToken(forceRefresh);
}

export function getGithubAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("gh_access_token");
}
