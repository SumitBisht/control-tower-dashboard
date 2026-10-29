import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, tokenStore, User } from "./api";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}
const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!tokenStore.get());

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  useEffect(() => {
    if (tokenStore.get()) api<User>("/auth/me").then(setUser).catch(logout).finally(() => setLoading(false));
    window.addEventListener("ct-logout", logout);
    return () => window.removeEventListener("ct-logout", logout);
  }, [logout]);

  const login = async (email: string, password: string) => {
    const r = await api<{ accessToken: string; user: User }>("/auth/login", { method: "POST", json: { email, password } });
    tokenStore.set(r.accessToken);
    setUser(r.user);
  };

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}
