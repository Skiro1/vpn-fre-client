import { useState, useCallback, useEffect, useRef } from "react";
import { VpnService } from "../../bindings/github.com/skkvpn/free-vpn-new";
import * as VpnModels from "../../bindings/github.com/skkvpn/free-vpn-new/internal/vpn/models";
import * as Models from "../../bindings/github.com/skkvpn/free-vpn-new/models";

export interface AppSettings {
  log_enabled: boolean;
  auto_connect: boolean;
  last_profile: string;
  auto_start: boolean;
}

export function useVpn() {
  const [status, setStatus] = useState<VpnModels.VpnStatus>(new VpnModels.VpnStatus());
  const [profiles, setProfiles] = useState<Models.ProfileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [settings, setSettings] = useState<AppSettings>({ log_enabled: true, auto_connect: false, last_profile: "", auto_start: false });
  const [updateAvailable, setUpdateAvailable] = useState("");
  const errorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoConnectDone = useRef(false);

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

  const loadSettings = useCallback(async () => {
    try {
      const s = await VpnService.GetSettings();
      setSettings({ log_enabled: s.log_enabled, auto_connect: s.auto_connect, last_profile: s.last_profile, auto_start: s.auto_start });
    } catch (e: any) {
      console.error("settings:", e);
    }
  }, []);

  const saveSettings = useCallback(async (s: AppSettings) => {
    const v = new VpnModels.Settings();
    v.log_enabled = s.log_enabled;
    v.auto_connect = s.auto_connect;
    v.last_profile = s.last_profile;
    v.auto_start = s.auto_start;
    try {
      await VpnService.SaveSettings(v);
      setSettings(s);
    } catch (e: any) {
      showError(e.message || "Save settings failed");
    }
  }, [showError]);

  const appVersion = "3.0.0";

  const semverGt = (a: string, b: string): boolean => {
    const sa = a.split(".").map(Number);
    const sb = b.split(".").map(Number);
    for (let i = 0; i < Math.max(sa.length, sb.length); i++) {
      if ((sa[i] || 0) > (sb[i] || 0)) return true;
      if ((sa[i] || 0) < (sb[i] || 0)) return false;
    }
    return false;
  };

  const checkUpdate = useCallback(async () => {
    try {
      const ctrl = new AbortController();
      const id = setTimeout(() => ctrl.abort(), 5000);
      const resp = await fetch("https://api.github.com/repos/Skiro1/vpn-free-client/releases/latest", { signal: ctrl.signal });
      clearTimeout(id);
      if (!resp.ok) return;
      const data = await resp.json();
      const latest = (data.tag_name || "").replace(/^v/, "");
      if (latest && semverGt(latest, appVersion)) setUpdateAvailable(latest);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refreshProfiles();
    refreshStatus();
    loadSettings();
    checkUpdate();
    pollingRef.current = setInterval(refreshStatus, 2000);

    const autoTimer = setTimeout(async () => {
      if (autoConnectDone.current) return;
      try {
        const s = await VpnService.GetSettings();
        if (s.auto_connect && s.last_profile) {
          autoConnectDone.current = true;
          await VpnService.Connect(s.last_profile);
          refreshStatus();
        }
      } catch {
        // ignore
      }
    }, 1000);

    return () => {
      clearTimeout(autoTimer);
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (errorTimer.current) clearTimeout(errorTimer.current);
    };
  }, [refreshProfiles, refreshStatus, loadSettings, checkUpdate]);

  return { status, profiles, loading, error, theme, settings, updateAvailable, toggleTheme, dismissError, register, connect, disconnect, deleteProfile, loadSettings, saveSettings };
}