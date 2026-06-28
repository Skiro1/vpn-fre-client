import { useState, useRef, useEffect } from "react";
import { useVpn, type AppSettings } from "./hooks/useVpn";

function formatBytes(b: number): string {
  if (b <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
  return (b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + units[i];
}

function polarToCartesian(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function sanitizeDns(val: string) {
  return val.replace(/[^a-zA-Z0-9.-]/g, "");
}

function describeArc(r: number, startDeg: number, endDeg: number, clockwise: boolean) {
  const start = polarToCartesian(50, 50, r, endDeg);
  const end = polarToCartesian(50, 50, r, startDeg);
  const large = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${r} ${r} 0 ${large} ${clockwise ? 1 : 0} ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

function App() {
  const { status, profiles, loading, error, theme, settings, toggleTheme, dismissError, register, connect, disconnect, deleteProfile, saveSettings } = useVpn();
  const [selectedProfile, setSelectedProfile] = useState("");
  const [newProfileName, setNewProfileName] = useState("");
  const [showRegister, setShowRegister] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [dnsDropdownOpen, setDnsDropdownOpen] = useState(false);
  const [dnsInput, setDnsInput] = useState("");
  const [ksInput, setKsInput] = useState(true);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const dnsDropdownRef = useRef<HTMLDivElement>(null);
  const prevTX = useRef(0);
  const prevRX = useRef(0);
  const prevTime = useRef(0);
  const [txSpeed, setTxSpeed] = useState(0);
  const [rxSpeed, setRxSpeed] = useState(0);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dnsDropdownRef.current && !dnsDropdownRef.current.contains(e.target as Node)) {
        setDnsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (!status.connected) return;
    const now = Date.now();
    if (prevTime.current > 0) {
      const dt = (now - prevTime.current) / 1000;
      if (dt > 0) {
        setTxSpeed(Math.max(0, (status.tx_bytes - prevTX.current) / dt));
        setRxSpeed(Math.max(0, (status.rx_bytes - prevRX.current) / dt));
      }
    }
    prevTX.current = status.tx_bytes;
    prevRX.current = status.rx_bytes;
    prevTime.current = now;
  }, [status.tx_bytes, status.rx_bytes, status.connected]);

  useEffect(() => {
    setDnsInput(settings.dns);
    setKsInput(settings.kill_switch);
  }, [settings]);

  const handleConnect = async () => {
    if (!selectedProfile) return;
    try { await connect(selectedProfile); } catch {}
  };

  const handleDisconnect = async () => {
    prevTX.current = 0;
    prevRX.current = 0;
    prevTime.current = 0;
    try { await disconnect(); } catch {}
  };

  const handleRegister = async () => {
    if (!newProfileName.trim()) return;
    const ok = await register(newProfileName.trim());
    if (ok) {
      setSelectedProfile(newProfileName.trim());
      setNewProfileName("");
      setShowRegister(false);
    }
  };

  const handleDeleteConfirm = () => {
    if (!showDeleteConfirm) return;
    deleteProfile(showDeleteConfirm);
    setSelectedProfile("");
    setShowDeleteConfirm("");
  };

  const handleSaveSettings = async () => {
    const s: AppSettings = { dns: sanitizeDns(dnsInput).trim() || "1.1.1.1", kill_switch: ksInput };
    await saveSettings(s);
    setShowSettings(false);
  };

  const selectProfile = (name: string) => {
    setSelectedProfile(name);
    setDropdownOpen(false);
  };

  const dark = theme === "dark";

  const maxArcDeg = 160;
  const maxSpeed = 15000000;
  const gapDeg = 5;
  const rxAngle = Math.max(gapDeg, Math.min((rxSpeed / maxSpeed) * maxArcDeg, maxArcDeg));
  const txAngle = Math.max(gapDeg, Math.min((txSpeed / maxSpeed) * maxArcDeg, maxArcDeg));

  return (
    <div className={`h-screen ${dark ? "bg-black text-white" : "bg-white text-black"} flex flex-col transition-colors duration-200`}>
      <div className="flex-1 flex flex-col max-w-md mx-auto w-full px-6 py-8">
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className={`w-9 h-9 rounded-full border-2 ${dark ? "border-neutral-700" : "border-neutral-300"} flex items-center justify-center`}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
              </svg>
            </div>
            <span className="text-lg font-bold tracking-tight">SKKVPN</span>
          </div>
          <div className="flex items-center gap-2">
            <div
              onClick={() => { setShowSettings(true); }}
              className={`w-9 h-9 rounded-full ${dark ? "bg-neutral-900 border-neutral-700 hover:text-white" : "bg-neutral-100 border-neutral-300 hover:text-black"} border-2 flex items-center justify-center ${dark ? "text-neutral-500" : "text-neutral-400"} cursor-pointer select-none transition-colors`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div
              onClick={toggleTheme}
              className={`w-9 h-9 rounded-full ${dark ? "bg-neutral-900 border-neutral-700 hover:text-white" : "bg-neutral-100 border-neutral-300 hover:text-black"} border-2 flex items-center justify-center ${dark ? "text-neutral-500" : "text-neutral-400"} cursor-pointer select-none transition-colors`}
            >
              {dark ? (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                </svg>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center gap-5">
          <div className="relative">
            {status.connected && (
              <svg className="absolute inset-0 w-48 h-48" viewBox="0 0 100 100" fill="none">
                <path
                  d={describeArc(44, 0, rxAngle, true)}
                  stroke="currentColor"
                  strokeWidth="4"
                  strokeLinecap="round"
                  className="transition-all duration-500"
                />
                <path
                  d={describeArc(44, 0, -txAngle, false)}
                  stroke="currentColor"
                  strokeWidth="4"
                  strokeLinecap="round"
                  className={`transition-all duration-500 ${dark ? "opacity-30" : "opacity-40"}`}
                />
                <path
                  d={describeArc(38, 0, rxAngle, true)}
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  className="transition-all duration-500"
                  opacity="0.15"
                />
                <path
                  d={describeArc(38, 0, -txAngle, false)}
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  className={`transition-all duration-500 ${dark ? "opacity-10" : "opacity-15"}`}
                />
              </svg>
            )}
            <div
              onClick={status.connected ? handleDisconnect : handleConnect}
              className={`w-48 h-48 rounded-full flex flex-col items-center justify-center transition-all duration-300 active:scale-95 ${(!selectedProfile && !status.connected) || loading ? "opacity-20 pointer-events-none" : "cursor-pointer"} ${
                dark ? "bg-white text-black" : "bg-black text-white"
              }`}
            >
              {loading ? (
                <svg className="animate-spin w-10 h-10" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <>
                  <svg className={"w-10 h-10 transition-transform " + (status.connected ? "scale-110" : "scale-100")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                  </svg>
                  <span className="text-xs font-medium mt-3 tracking-[0.15em] uppercase">
                    {status.connected ? "Connected" : "Connect"}
                  </span>
                </>
              )}
            </div>
          </div>

          {status.connected && (
            <div className="flex items-center justify-center gap-6 text-center">
              <div>
                <div className={`text-[11px] font-medium tracking-wider uppercase ${dark ? "text-neutral-500" : "text-neutral-400"}`}>Download</div>
                <div className="text-sm font-semibold tabular-nums tracking-tight">{formatBytes(status.rx_bytes)}</div>
              </div>
              <div className={`w-px h-8 ${dark ? "bg-neutral-800" : "bg-neutral-200"}`} />
              <div>
                <div className={`text-[11px] font-medium tracking-wider uppercase ${dark ? "text-neutral-500" : "text-neutral-400"}`}>Upload</div>
                <div className="text-sm font-semibold tabular-nums tracking-tight">{formatBytes(status.tx_bytes)}</div>
              </div>
            </div>
          )}

          {!status.connected && (
            <div className="w-full space-y-3">
              <div className="relative" ref={dropdownRef}>
                <div
                  onClick={() => setDropdownOpen((o) => !o)}
                  className={`w-full flex items-center justify-between ${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-xl px-4 py-3 text-sm cursor-pointer select-none transition-colors ${
                    dropdownOpen ? "ring-2 ring-neutral-500" : ""
                  }`}
                >
                  <span className={selectedProfile ? "" : dark ? "text-neutral-500" : "text-neutral-400"}>
                    {selectedProfile || "Select profile"}
                  </span>
                  <svg className={`w-4 h-4 ${dark ? "text-neutral-500" : "text-neutral-400"} transition-transform ${dropdownOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
                {dropdownOpen && (
                  <div className={`absolute z-10 w-full mt-1 ${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-xl overflow-hidden shadow-xl`}>
                    {profiles.length === 0 ? (
                      <div className={`px-4 py-3 text-sm ${dark ? "text-neutral-500" : "text-neutral-400"}`}>No profiles</div>
                    ) : (
                      profiles.map((p) => (
                        <div
                          key={p.name}
                          onClick={() => selectProfile(p.name)}
                          className={`w-full text-left px-4 py-3 text-sm cursor-pointer select-none transition-colors ${
                            p.name === selectedProfile
                              ? dark ? "bg-neutral-800 text-white" : "bg-neutral-200 text-black"
                              : dark ? "text-white hover:bg-neutral-800" : "text-black hover:bg-neutral-200"
                          }`}
                        >
                          {p.name}{p.warp_plus ? " — WARP+" : ""}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <div
                  onClick={() => setShowRegister(true)}
                  className={`flex-1 px-4 py-3 rounded-lg border-2 ${dark ? "border-neutral-700 hover:bg-neutral-900" : "border-neutral-300 hover:bg-neutral-100"} text-sm font-medium ${dark ? "text-neutral-500" : "text-neutral-400"} cursor-pointer select-none transition-colors`}
                >
                  + New profile
                </div>
                {selectedProfile && (
                  <div
                    onClick={() => setShowDeleteConfirm(selectedProfile)}
                    className={`px-4 py-3 rounded-lg border-2 ${dark ? "border-neutral-700 bg-neutral-900 text-neutral-500 hover:text-red-400" : "border-neutral-300 bg-neutral-100 text-neutral-500 hover:text-red-500"} cursor-pointer select-none transition-colors`}
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="shrink-0 pt-6" />
      </div>

      {showRegister && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-6 z-50">
          <div className={`${dark ? "bg-black border-neutral-700" : "bg-white border-neutral-300"} border-2 rounded-2xl w-full max-w-sm p-5 space-y-4`}>
            <div className="flex items-center justify-between">
              <span className="text-base font-semibold">New profile</span>
              <div onClick={() => setShowRegister(false)} className={`${dark ? "text-neutral-500 hover:text-white" : "text-neutral-400 hover:text-black"} cursor-pointer select-none`}>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
            </div>
            <input
              type="text"
              value={newProfileName}
              onChange={(e) => setNewProfileName(e.target.value)}
              placeholder="Profile name"
              className={`w-full ${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-lg px-4 py-3 text-sm placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-neutral-500 transition-colors`}
              onKeyDown={(e) => e.key === "Enter" && handleRegister()}
              autoFocus
            />
            <div
              onClick={handleRegister}
              className={`w-full py-3 rounded-lg text-sm font-medium text-center ${!newProfileName.trim() || loading ? "opacity-20" : "cursor-pointer"} transition-all active:scale-[0.98] ${
                dark ? "bg-white text-black" : "bg-black text-white"
              }`}
            >
              {loading ? "Registering..." : "Register with WARP"}
            </div>
          </div>
        </div>
      )}

      {showSettings && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-6 z-50">
          <div className={`${dark ? "bg-black border-neutral-700" : "bg-white border-neutral-300"} border-2 rounded-2xl w-full max-w-sm p-5 space-y-5`}>
            <div className="flex items-center justify-between">
              <span className="text-base font-semibold">Settings</span>
              <div onClick={() => setShowSettings(false)} className={`${dark ? "text-neutral-500 hover:text-white" : "text-neutral-400 hover:text-black"} cursor-pointer select-none`}>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
            </div>

            <div className="space-y-2">
              <label className={`block text-sm font-medium ${dark ? "text-neutral-400" : "text-neutral-500"}`}>DNS server</label>
              <div className="relative" ref={dnsDropdownRef}>
                <div
                  onClick={() => setDnsDropdownOpen((o) => !o)}
                  className={`w-full flex items-center justify-between ${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-lg px-4 py-3 text-sm cursor-pointer select-none transition-colors ${
                    dnsDropdownOpen ? "ring-2 ring-neutral-500" : ""
                  }`}
                >
                  <span className={dnsInput ? "" : dark ? "text-neutral-500" : "text-neutral-400"}>
                    {dnsInput || "Select or type DNS"}
                  </span>
                  <svg className={`w-4 h-4 ${dark ? "text-neutral-500" : "text-neutral-400"} transition-transform ${dnsDropdownOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
                {dnsDropdownOpen && (
                  <div className={`absolute z-10 w-full mt-1 ${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-xl overflow-hidden shadow-xl`}>
                    {[
                      { label: "Cloudflare", value: "1.1.1.1" },
                      { label: "Google", value: "8.8.8.8" },
                      { label: "Quad9", value: "9.9.9.9" },
                      { label: "OpenDNS", value: "208.67.222.222" },
                      { label: "AdGuard", value: "94.140.14.14" },
                      { label: "SkyDNS", value: "193.58.251.251" },
                      { label: "Xbox DNS", value: "111.88.96.50" },
                    ].map((p) => (
                      <div
                        key={p.value}
                        onClick={() => { setDnsInput(p.value); setDnsDropdownOpen(false); }}
                        className={`w-full text-left px-4 py-3 text-sm cursor-pointer select-none transition-colors ${
                          dnsInput === p.value
                            ? dark ? "bg-neutral-800 text-white" : "bg-neutral-200 text-black"
                            : dark ? "text-white hover:bg-neutral-800" : "text-black hover:bg-neutral-200"
                        }`}
                      >
                        <span>{p.label}</span>
                        <span className={`ml-2 text-xs ${dark ? "text-neutral-500" : "text-neutral-400"}`}>{p.value}</span>
                      </div>
                    ))}
                    <div className={`border-t ${dark ? "border-neutral-700" : "border-neutral-300"}`}>
                      <input
                        type="text"
                        value={dnsInput}
                        onChange={(e) => setDnsInput(sanitizeDns(e.target.value))}
                        placeholder="Custom (IP or domain)"
                        className={`w-full ${dark ? "bg-transparent text-white placeholder-neutral-500" : "bg-transparent text-black placeholder-neutral-400"} px-4 py-3 text-sm focus:outline-none`}
                        onFocus={() => setDnsDropdownOpen(true)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { setDnsDropdownOpen(false); handleSaveSettings(); }
                        }}
                        autoFocus
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <div className={`text-sm font-medium ${dark ? "text-neutral-400" : "text-neutral-500"}`}>Kill Switch</div>
                <div className={`text-[11px] ${dark ? "text-neutral-600" : "text-neutral-400"}`}>Block internet if VPN drops</div>
              </div>
              <div
                onClick={() => setKsInput(!ksInput)}
                className={`w-12 h-6 rounded-full transition-colors duration-200 cursor-pointer flex items-center shrink-0 ${
                  ksInput
                    ? dark ? "bg-neutral-600" : "bg-black"
                    : dark ? "bg-neutral-800 border-neutral-700" : "bg-neutral-200 border-neutral-300"
                } border-2`}
              >
                <div className={`w-4 h-4 rounded-full transition-all duration-200 ${
                  ksInput ? "translate-x-6" : "translate-x-0.5"
                } ${
                  ksInput
                    ? dark ? "bg-white" : "bg-white"
                    : dark ? "bg-neutral-500" : "bg-neutral-400"
                }`} />
              </div>
            </div>

            <div
              onClick={handleSaveSettings}
              className={`w-full py-3 rounded-lg text-sm font-medium text-center cursor-pointer select-none transition-all active:scale-[0.98] ${
                dark ? "bg-white text-black" : "bg-black text-white"
              }`}
            >
              Save
            </div>
          </div>
        </div>
      )}

      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-6 z-50">
          <div className={`${dark ? "bg-black border-neutral-700" : "bg-white border-neutral-300"} border-2 rounded-2xl w-full max-w-sm p-5 space-y-5`}>
            <div className="flex items-center justify-between">
              <span className="text-base font-semibold">Delete profile</span>
              <div onClick={() => setShowDeleteConfirm("")} className={`${dark ? "text-neutral-500 hover:text-white" : "text-neutral-400 hover:text-black"} cursor-pointer select-none`}>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
            </div>
            <p className="text-sm leading-relaxed">
              Are you sure you want to delete <span className="font-semibold">{showDeleteConfirm}</span>?
            </p>
            <div className="flex gap-3">
              <div
                onClick={() => setShowDeleteConfirm("")}
                className={`flex-1 px-4 py-3 rounded-lg border-2 text-sm font-medium text-center ${dark ? "border-neutral-700 text-neutral-500 hover:text-white" : "border-neutral-300 text-neutral-400 hover:text-black"} cursor-pointer select-none transition-colors`}
              >
                Cancel
              </div>
              <div
                onClick={handleDeleteConfirm}
                className={`flex-1 px-4 py-3 rounded-lg text-sm font-medium text-center cursor-pointer select-none transition-all active:scale-[0.98] ${
                  dark ? "bg-white text-black" : "bg-black text-white"
                }`}
              >
                Delete
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[calc(100%-48px)] max-w-sm z-50">
          <div className={`${dark ? "bg-black border-neutral-700" : "bg-white border-neutral-300"} border-2 rounded-lg shadow-2xl px-4 py-3 flex items-start gap-3`}>
            <span className={dark ? "text-neutral-500" : "text-neutral-400"}>⚠</span>
            <p className={`text-sm flex-1 leading-relaxed break-words ${dark ? "text-white" : "text-black"}`}>{error}</p>
            <div onClick={dismissError} className={`${dark ? "text-neutral-500 hover:text-white" : "text-neutral-400 hover:text-black"} cursor-pointer select-none shrink-0`}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
