import { useState, useRef, useEffect } from "react";
import { useVpn } from "./hooks/useVpn";

function formatBytes(b: number): string {
  if (b <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), units.length - 1);
  return (b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + units[i];
}

function App() {
  const { status, profiles, loading, error, theme, toggleTheme, dismissError, register, connect, disconnect, deleteProfile } = useVpn();
  const [selectedProfile, setSelectedProfile] = useState("");
  const [newProfileName, setNewProfileName] = useState("");
  const [showRegister, setShowRegister] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
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

  const selectProfile = (name: string) => {
    setSelectedProfile(name);
    setDropdownOpen(false);
  };

  const dark = theme === "dark";

  const txPct = status.tx_bytes + status.rx_bytes > 0
    ? (status.tx_bytes / (status.tx_bytes + status.rx_bytes)) * 100 : 50;
  const rxPct = 100 - txPct;

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

        <div className="flex-1 flex flex-col items-center justify-center gap-5">
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

          {status.connected && (
            <div className="w-full space-y-3">
              <div className={`${dark ? "bg-neutral-900 border-neutral-700" : "bg-neutral-100 border-neutral-300"} border-2 rounded-xl p-4`}>
                <div className="flex items-center gap-4 mb-3">
                  <div className="flex-1 h-1.5 rounded-full overflow-hidden flex">
                    <div
                      className="bg-white dark:bg-black transition-all duration-500"
                      style={{ width: rxPct + "%" }}
                    />
                    <div
                      className={`${dark ? "bg-neutral-600" : "bg-neutral-400"} transition-all duration-500`}
                      style={{ width: txPct + "%" }}
                    />
                  </div>
                </div>

                <div className="flex gap-4">
                  <div className="flex-1 flex items-center gap-3 min-w-0">
                    <div className={`w-8 h-8 rounded-lg ${dark ? "bg-neutral-800" : "bg-neutral-200"} flex items-center justify-center shrink-0`}>
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 13.5L12 21m0 0l-7.5-7.5M12 21V3" />
                      </svg>
                    </div>
                    <div className="min-w-0">
                      <div className={`text-[11px] font-medium tracking-wider uppercase ${dark ? "text-neutral-500" : "text-neutral-400"}`}>Download</div>
                      <div className="text-sm font-semibold tabular-nums tracking-tight">{formatBytes(status.rx_bytes)}</div>
                      {rxSpeed > 0 && (
                        <div className={`text-[10px] tabular-nums ${dark ? "text-neutral-600" : "text-neutral-400"}`}>{formatBytes(rxSpeed)}/s</div>
                      )}
                    </div>
                  </div>

                  <div className="flex-1 flex items-center gap-3 min-w-0">
                    <div className={`w-8 h-8 rounded-lg ${dark ? "bg-neutral-800" : "bg-neutral-200"} flex items-center justify-center shrink-0`}>
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
                      </svg>
                    </div>
                    <div className="min-w-0">
                      <div className={`text-[11px] font-medium tracking-wider uppercase ${dark ? "text-neutral-500" : "text-neutral-400"}`}>Upload</div>
                      <div className="text-sm font-semibold tabular-nums tracking-tight">{formatBytes(status.tx_bytes)}</div>
                      {txSpeed > 0 && (
                        <div className={`text-[10px] tabular-nums ${dark ? "text-neutral-600" : "text-neutral-400"}`}>{formatBytes(txSpeed)}/s</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className={`text-center text-xs font-mono tabular-nums ${dark ? "text-neutral-600" : "text-neutral-400"}`}>
                {status.uptime}
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
