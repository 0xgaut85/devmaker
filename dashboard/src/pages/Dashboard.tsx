import { useState, useEffect, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";

interface LogEntry {
  id: string;
  message: string;
  level: string;
  timestamp: string;
}

export default function Dashboard() {
  const { accountId } = useParams<{ accountId: string }>();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<{ connected: boolean; running: boolean }>({ connected: false, running: false });
  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!accountId) return;
    let cancelled = false;
    let retryDelay = 1000;

    api.logs.get(accountId, 200).then(setLogs).catch(console.error);
    api.accounts.status(accountId).then(setStatus).catch(console.error);

    const statusInterval = setInterval(() => {
      api.accounts.status(accountId).then(setStatus).catch(console.error);
    }, 5000);

    function connectWs() {
      if (cancelled) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/logs/${accountId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => { retryDelay = 1000; };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "log") {
            setLogs((prev) => [...prev.slice(-499), {
              id: Date.now().toString(),
              message: data.message,
              level: data.level,
              timestamp: data.timestamp,
            }]);
          }
        } catch { /* ignore malformed messages */ }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setTimeout(connectWs, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30000);
      };

      ws.onerror = () => { ws.close(); };
    }

    connectWs();

    return () => {
      cancelled = true;
      clearInterval(statusInterval);
      wsRef.current?.close();
    };
  }, [accountId]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  function levelColor(level: string) {
    switch (level) {
      case "error": return "text-red-400";
      case "warning": return "text-amber-400";
      default: return "text-neutral-300";
    }
  }

  function formatTime(ts: string) {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleTimeString();
    } catch {
      return ts;
    }
  }

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/accounts" className="text-neutral-500 hover:text-white text-sm">← Back</Link>
        <h2 className="text-xl font-semibold text-white">Live Dashboard</h2>
        <div className="ml-auto flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${status.connected ? "bg-green-500" : "bg-neutral-600"}`} />
          <span className="text-xs text-neutral-400">{status.connected ? "Extension connected" : "Extension offline"}</span>
          {status.running && <span className="text-xs text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded-md">Running</span>}
        </div>
      </div>

      <div className="bg-neutral-900 border border-neutral-800 rounded-xl overflow-hidden">
        <div className="p-3 border-b border-neutral-800 flex items-center justify-between">
          <span className="text-xs text-neutral-400 font-medium">Logs</span>
          <span className="text-xs text-neutral-600">{logs.length} entries</span>
        </div>
        <div className="h-[600px] overflow-y-auto p-3 font-mono text-xs space-y-0.5">
          {logs.map((log) => (
            <div key={log.id} className={`flex gap-2 ${levelColor(log.level)}`}>
              <span className="text-neutral-600 shrink-0 w-20">{formatTime(log.timestamp)}</span>
              <span className="break-all">{log.message}</span>
            </div>
          ))}
          {logs.length === 0 && (
            <div className="text-neutral-600 text-center py-8">No logs yet. Start a sequence to see activity.</div>
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
}
