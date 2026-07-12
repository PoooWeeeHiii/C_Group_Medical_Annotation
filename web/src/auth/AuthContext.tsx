import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiGet, apiPost, getToken, setToken } from "../api/client";
import type { User } from "../types";

interface AuthState {
  user: User | null;
  token: string;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<boolean>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setTokenState] = useState(getToken());
  const [loading, setLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    const current = getToken();
    if (!current) {
      setUser(null);
      setTokenState("");
      return false;
    }
    try {
      const data = await apiGet<{ user: User }>("/api/me");
      setUser(data.user);
      setTokenState(current);
      return true;
    } catch {
      setToken("");
      setUser(null);
      setTokenState("");
      return false;
    }
  }, []);

  useEffect(() => {
    refreshMe().finally(() => setLoading(false));
  }, [refreshMe]);

  const login = useCallback(async (username: string, password: string) => {
    const data = await apiPost<{ access_token: string; user: User }>("/api/auth/login", {
      username,
      password,
    });
    setToken(data.access_token);
    setTokenState(data.access_token);
    setUser(data.user);
  }, []);

  const logout = useCallback(() => {
    setToken("");
    setTokenState("");
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, token, loading, login, logout, refreshMe }),
    [user, token, loading, login, logout, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useRole() {
  const { user } = useAuth();
  const role = user?.role || null;
  return {
    role,
    canAnnotate: role === "annotator" || role === "admin" || role === "reviewer",
    canReview: role === "reviewer" || role === "admin",
    canManageTasks: role === "reviewer" || role === "admin",
    canManageUsers: role === "admin",
    canManageLabels: role === "admin",
  };
}
