import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

interface Account {
  id: string;
  name: string;
  api_key: string;
  connected: boolean;
  running: boolean;
}

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [newName, setNewName] = useState("");
  const [loading, setLoading] = useState(true);
  const [seqCounts, setSeqCounts] = useState<Record<string, number>>({});

  async function load() {
    try {
      const data = await api.accounts.list();
      setAccounts(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); const i = setInterval(load, 5000); return () => clearInterval(i); }, []);

  async function create() {
    if (!newName.trim()) return;
    await api.accounts.create(newName.trim());
    setNewName("");
    load();
  }

  async function remove(id: string) {
    if (!confirm("Delete this account?")) return;
    await api.accounts.delete(id);
    load();
  }

  async function start(id: string) {
    const count = seqCounts[id] || 1;
    await api.accounts.start(id, count);
    load();
  }

  async function stop(id: string) {
    await api.accounts.stop(id);
    load();
  }

  if (loading) return <div className="text-neutral-500 text-sm">Loading...</div>;

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-6">Accounts</h2>

      <div className="flex gap-3 mb-8">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Account name"
          className="bg-neutral-900 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-neutral-600 flex-1"
          onKeyDown={(e) => e.key === "Enter" && create()}
        />
        <button
          onClick={create}
          className="bg-white text-black font-medium rounded-lg px-4 py-2 text-sm hover:bg-neutral-200 transition-colors"
        >
          Add Account
        </button>
      </div>

      <div className="space-y-3">
        {accounts.map((a) => (
          <div key={a.id} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex items-center gap-4">
            <div className={`w-2.5 h-2.5 rounded-full ${a.connected ? "bg-green-500" : "bg-neutral-600"}`} />
            <div className="flex-1 min-w-0">
              <div className="text-white font-medium text-sm">{a.name}</div>
              <div className="text-neutral-500 text-xs font-mono truncate">ID: {a.id}</div>
            </div>

            <div className="flex items-center gap-2">
              {a.running ? (
                <span className="text-xs text-amber-400 px-2 py-1 bg-amber-400/10 rounded-md">Running</span>
              ) : a.connected ? (
                <span className="text-xs text-green-400 px-2 py-1 bg-green-400/10 rounded-md">Connected</span>
              ) : (
                <span className="text-xs text-neutral-500 px-2 py-1 bg-neutral-800 rounded-md">Offline</span>
              )}
            </div>

            <div className="flex items-center gap-2 ml-2">
              <input
                type="number"
                min={1}
                max={50}
                value={seqCounts[a.id] || 1}
                onChange={(e) => setSeqCounts({ ...seqCounts, [a.id]: parseInt(e.target.value) || 1 })}
                className="w-14 bg-neutral-800 border border-neutral-700 rounded-md px-2 py-1 text-xs text-white text-center outline-none"
              />
              {a.running ? (
                <button onClick={() => stop(a.id)} className="bg-red-500/20 text-red-400 text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-red-500/30">
                  Stop
                </button>
              ) : (
                <button onClick={() => start(a.id)} disabled={!a.connected} className="bg-green-500/20 text-green-400 text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-green-500/30 disabled:opacity-30 disabled:cursor-not-allowed">
                  Start
                </button>
              )}
            </div>

            <div className="flex items-center gap-1 ml-2">
              <Link to={`/dashboard/${a.id}`} className="text-xs text-neutral-400 hover:text-white px-2 py-1 rounded-md hover:bg-neutral-800 transition-colors">
                Logs
              </Link>
              <Link to={`/settings/${a.id}`} className="text-xs text-neutral-400 hover:text-white px-2 py-1 rounded-md hover:bg-neutral-800 transition-colors">
                Settings
              </Link>
              <button onClick={() => remove(a.id)} className="text-xs text-neutral-500 hover:text-red-400 px-2 py-1 rounded-md hover:bg-neutral-800 transition-colors">
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {accounts.length === 0 && (
        <p className="text-neutral-500 text-sm text-center py-12">No accounts yet. Create one above.</p>
      )}
    </div>
  );
}
