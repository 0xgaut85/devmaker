import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { getApiKey, setApiKey } from "./api";

export default function App() {
  const location = useLocation();
  const [key, setKey] = useState(getApiKey());
  const [keyInput, setKeyInput] = useState("");

  if (!key) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl p-8 w-96">
          <h1 className="text-xl font-semibold text-white mb-1">DevMaker</h1>
          <p className="text-sm text-neutral-400 mb-6">Enter your API key to continue</p>
          <input
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder="API key"
            className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-neutral-500 mb-4"
            onKeyDown={(e) => e.key === "Enter" && keyInput && setApiKey(keyInput)}
          />
          <button
            onClick={() => keyInput && setApiKey(keyInput)}
            className="w-full bg-white text-black font-medium rounded-lg py-2 text-sm hover:bg-neutral-200 transition-colors"
          >
            Continue
          </button>
        </div>
      </div>
    );
  }

  const navItems = [
    { path: "/accounts", label: "Accounts" },
  ];

  return (
    <div className="min-h-screen bg-black">
      <nav className="border-b border-neutral-800 px-6 py-3 flex items-center gap-6">
        <span className="text-white font-semibold text-lg">DevMaker</span>
        <div className="flex gap-4 ml-6">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`text-sm transition-colors ${
                location.pathname.startsWith(item.path) ? "text-white" : "text-neutral-500 hover:text-neutral-300"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
        <button
          onClick={() => { localStorage.removeItem("devmaker_api_key"); window.location.reload(); }}
          className="ml-auto text-xs text-neutral-500 hover:text-neutral-300"
        >
          Logout
        </button>
      </nav>
      <main className="max-w-5xl mx-auto px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
