import { useState, useCallback, useEffect, useRef } from "react";
import { VpnService } from "../../bindings/github.com/skkvpn/free-vpn-new";
import * as VpnModels from "../../bindings/github.com/skkvpn/free-vpn-new/internal/vpn/models";
import * as Models from "../../bindings/github.com/skkvpn/free-vpn-new/models";

export function useVpn() {
  const [status, setStatus] = useState<VpnModels.VpnStatus>(new VpnModels.VpnStatus());
  const [profiles, setProfiles] = useState<Models.ProfileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const errorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showError = useCallback((msg: string) => {
    setError(msg);
    if (errorTimer.current) clearTimeout(errorTimer.current);
    errorTimer.current = setTimeout(() => setError(null), 5000);
  }, []);

  const dismissError = useCallback(() => {
    setError(null);
    if (errorTimer.current) clearTimeout(errorTimer.current);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(t => t === "dark" ? "light" : "dark");
  }, []);

  const refreshProfiles = useCallback(async () => {
    try {
      const list = await VpnService.ListProfiles();
      setProfiles(list.filter((p): p is Models.ProfileInfo => p !== null));
    } catch (e: any) {
      console.error("profiles:", e);
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await VpnService.GetStatus();
      if (s) setStatus(s);
    } catch (e: any) {
      console.error("status:", e);
    }
  }, []);

  const friendlyError = (msg: string): string => {
    if (/TLS handshake timeout/i.test(msg)) return "Registration timed out. Check your internet connection and try again.";
    if (/no such host|lookup.*failed/i.test(msg)) return "Network error. Check your internet connection.";
    if (/connection refused|connectex.*connection refused/i.test(msg)) return "Connection refused by server. Try again later.";
    return msg;
  };

  const register = useCallback(async (name: string, license?: string) => {
    setLoading(true);
    try {
      await VpnService.Register(name, license || "");
      await refreshProfiles();
      return true;
    } catch (e: any) {
      showError(friendlyError(e.message || "Registration failed"));
      return false;
    } finally {
      setLoading(false);
    }
  }, [refreshProfiles, showError]);

  const connect = useCallback(async (name: string) => {
    setLoading(true);
    try {
      await VpnService.Connect(name);
      await refreshStatus();
    } catch (e: any) {
      showError(e.message || "Connection failed");
    } finally {
      setLoading(false);
    }
  }, [refreshStatus, showError]);

  const disconnect = useCallback(async () => {
    setLoading(true);
    try {
      await VpnService.Disconnect();
      await refreshStatus();
    } catch (e: any) {
      showError(e.message || "Disconnect failed");
    } finally {
      setLoading(false);
    }
  }, [refreshStatus, showError]);

  const deleteProfile = useCallback(async (name: string) => {
    try {
      await VpnService.DeleteProfile(name);
      await refreshProfiles();
    } catch (e: any) {
      showError(e.message || "Delete failed");
    }
  }, [refreshProfiles, showError]);

  useEffect(() => {
    refreshProfiles();
    refreshStatus();
    pollingRef.current = setInterval(refreshStatus, 2000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (errorTimer.current) clearTimeout(errorTimer.current);
    };
  }, [refreshProfiles, refreshStatus]);

  return { status, profiles, loading, error, theme, toggleTheme, dismissError, register, connect, disconnect, deleteProfile };
}
