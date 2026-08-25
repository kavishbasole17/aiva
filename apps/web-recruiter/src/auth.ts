import { useSyncExternalStore } from "react";
import { setAccessToken } from "./api/client";

const TOKEN_KEY = "aiva.recruiter.access";

interface AuthState {
  token: string | null;
}

let state: AuthState = { token: localStorage.getItem(TOKEN_KEY) };
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function signIn(token: string): void {
  state = { token };
  localStorage.setItem(TOKEN_KEY, token);
  setAccessToken(token);
  emit();
}

export function signOut(): void {
  state = { token: null };
  localStorage.removeItem(TOKEN_KEY);
  setAccessToken(null);
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  );
}

if (state.token) {
  setAccessToken(state.token);
}
