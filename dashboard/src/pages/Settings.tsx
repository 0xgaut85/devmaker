import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";

export default function Settings() {
  const { accountId } = useParams<{ accountId: string }>();
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!accountId) return;
    api.config.get(accountId)
      .then(setConfig)
      .catch((err: any) => setLoadError(err.message || "Failed to load config"));
  }, [accountId]);

  async function save() {
    if (!accountId || !config) return;
    setSaving(true);
    setSaveError("");
    try {
      await api.config.update(accountId, config);
      // Re-fetch so derived totals (daily_max_*) reflect the new seq_* values
      // immediately instead of staying stale until the user reloads.
      const fresh = await api.config.get(accountId);
      setConfig(fresh);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: any) {
      console.error(err);
      setSaveError(err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function update(key: string, value: any) {
    setConfig((c) => c ? { ...c, [key]: value } : c);
  }

  if (loadError) return <div className="text-red-400 text-sm">Error: {loadError}</div>;
  if (!config) return <div className="text-neutral-500 text-sm">Loading...</div>;

  const mode = config.farming_mode || "dev";

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/accounts" className="text-neutral-500 hover:text-white text-sm">← Back</Link>
        <h2 className="text-xl font-semibold text-white">Settings</h2>
      </div>

      <div className="space-y-8">
        {/* 1. MODE — top-level switch */}
        <Section title="Mode" subtitle="Pick the farming mode. Sections below adapt to the mode you choose.">
          <Select label="Farming Mode" value={mode} onChange={(v) => update("farming_mode", v)}
            options={["dev", "degen", "rt_farm", "sniper"]} />
          <Toggle label="Use Following Tab" value={config.use_following_tab ?? true} onChange={(v) => update("use_following_tab", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Scrape from "Following" instead of "For You". Better for fresh accounts with curated follows.</p>
          <Toggle label="Allow trading / price posts" value={config.allow_trading_price_posts ?? false} onChange={(v) => update("allow_trading_price_posts", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">If off (default), skip RT/QRT/comments on obvious crypto price or chart posts. Turn on for CT-style accounts.</p>
          <Toggle label="LLM: exclude politics / geopolitics" value={config.exclude_political_timeline ?? true} onChange={(v) => update("exclude_political_timeline", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">When on, the topic classifier will not assign categories to political or geopolitical posts (reduces algo doom-scroll). Off only if you intentionally engage in that space.</p>
        </Section>

        {/* 2. SEQUENCE COMPOSITION — most-tuned setting */}
        {(mode === "dev" || mode === "degen") && (
          <Section title="Sequence Composition" subtitle="Exact actions per sequence. Daily totals derive from these. Rare specialty actions (threads, media, rephrase, qrt) run before bulk comments so they always get a fresh post pool.">
            <Number label="Original tweets (text)" value={config.seq_text_tweets} onChange={(v) => update("seq_text_tweets", v)} />
            <Number label="Rephrased tweets" value={config.seq_rephrase_tweets} onChange={(v) => update("seq_rephrase_tweets", v)} />
            <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Take a popular post + its media (if present) and rewrite it in your voice.</p>
            <Number label="Media tweets" value={config.seq_media_tweets} onChange={(v) => update("seq_media_tweets", v)} />
            <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Original tweet that REQUIRES attaching media from a source post. Skips with a clear log if no eligible source has images.</p>
            <Number label="Quote retweets" value={config.seq_qrts} onChange={(v) => update("seq_qrts", v)} />
            <Number label="Retweets" value={config.seq_rts} onChange={(v) => update("seq_rts", v)} />
            <Number label="Comments" value={config.seq_comments} onChange={(v) => update("seq_comments", v)} />
            <Number label="Follows" value={config.seq_follows} onChange={(v) => update("seq_follows", v)} />
            <Number label="Threads" value={config.seq_threads} onChange={(v) => update("seq_threads", v)} />
            <DerivedTotals config={config} />
          </Section>
        )}

        {/* 3. TOPICS — what content the bot engages with */}
        {(mode === "dev" || mode === "sniper") && (
          <Section title="Topics" subtitle="Add topics and set weight (1-5). Only posts matching these topics will be used. Click the red × to remove.">
            <TopicsPicker value={config.topics || {}} onChange={(v) => update("topics", v)} preset={TOPICS_GENERAL} />
          </Section>
        )}

        {mode === "degen" && (
          <Section title="Degen Topics" subtitle="Topics for degen farming mode.">
            <TopicsPicker value={config.degen_topics || {}} onChange={(v) => update("degen_topics", v)} preset={TOPICS_DEGEN} />
          </Section>
        )}

        {/* 4. VOICE — high impact on output quality */}
        {mode === "dev" && (
          <Section title="Voice" subtitle="Voice + Don't are enforced after generation. 'no emojis at all', 'no hashtags', etc. become hard rules.">
            <TextArea label="Voice Description" value={config.voice_description} onChange={(v) => update("voice_description", v)} />
            <TextArea label="Do" value={config.dev_do} onChange={(v) => update("dev_do", v)} />
            <TextArea label="Don't" value={config.dev_dont} onChange={(v) => update("dev_dont", v)} />
            <TextArea label="Bad Examples" value={config.bad_examples} onChange={(v) => update("bad_examples", v)} />
            <TextArea label="Good Examples" value={config.good_examples} onChange={(v) => update("good_examples", v)} />
          </Section>
        )}

        {mode === "degen" && (
          <Section title="Degen Voice">
            <TextArea label="Degen Voice" value={config.degen_voice_description} onChange={(v) => update("degen_voice_description", v)} />
            <TextArea label="Do" value={config.degen_do} onChange={(v) => update("degen_do", v)} />
            <TextArea label="Don't" value={config.degen_dont} onChange={(v) => update("degen_dont", v)} />
          </Section>
        )}

        {/* 5. PERSONALITY — voice fine-tuning */}
        {(mode === "dev" || mode === "degen") && (
          <Section title="Personality" subtitle="Shape the account's unique voice. These traits influence how the LLM generates content.">
            <Slider label="Humor" sublabel="Serious → Witty" value={config.personality_humor} onChange={(v) => update("personality_humor", v)} />
            <Slider label="Sarcasm" sublabel="Earnest → Sarcastic" value={config.personality_sarcasm} onChange={(v) => update("personality_sarcasm", v)} />
            <Slider label="Confidence" sublabel="Humble → Bold" value={config.personality_confidence} onChange={(v) => update("personality_confidence", v)} />
            <Slider label="Warmth" sublabel="Detached → Friendly" value={config.personality_warmth} onChange={(v) => update("personality_warmth", v)} />
            <Slider label="Controversy" sublabel="Safe → Provocative" value={config.personality_controversy} onChange={(v) => update("personality_controversy", v)} />
            <Slider label="Intellect" sublabel="Casual → Analytical" value={config.personality_intellect} onChange={(v) => update("personality_intellect", v)} />
            <Slider label="Brevity" sublabel="Verbose → Punchy" value={config.personality_brevity} onChange={(v) => update("personality_brevity", v)} />
            <Slider label="Edginess" sublabel="Wholesome → Raw" value={config.personality_edginess} onChange={(v) => update("personality_edginess", v)} />
          </Section>
        )}

        {/* 6. ACTIVE HOURS + 7. TIMING — when and how often */}
        <Section title="Active Hours" subtitle="Restrict the bot to specific local hours. Off = run 24/7.">
          <Toggle label="Enabled" value={config.active_hours_enabled} onChange={(v) => update("active_hours_enabled", v)} />
          <Number label="Start Hour (0-23)" value={config.active_hours_start} onChange={(v) => update("active_hours_start", Math.max(0, Math.min(23, v)))} />
          <Number label="End Hour (0-24)" value={config.active_hours_end} onChange={(v) => update("active_hours_end", Math.max(0, Math.min(24, v)))} />
          <Field label="Timezone (IANA)" value={config.active_hours_timezone} onChange={(v) => update("active_hours_timezone", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">e.g. "America/New_York", "Europe/Paris", "UTC".</p>
        </Section>

        <Section title="Timing" subtitle="Pacing knobs. Lower = more aggressive / less human-looking.">
          <Number label="Action Delay (s)" value={config.action_delay_seconds} onChange={(v) => update("action_delay_seconds", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Floor for the random pause between actions inside a sequence.</p>
          <Number label="Sequence Delay (min)" value={config.sequence_delay_minutes} onChange={(v) => update("sequence_delay_minutes", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Wait between sequences when running a multi-sequence batch.</p>
          <Number label="Min Engagement Likes" value={config.min_engagement_likes} onChange={(v) => update("min_engagement_likes", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Posts with fewer likes than this are filtered out before topic classification.</p>
        </Section>

        {/* 8. INTELLIGENCE — opt-in advanced */}
        <Section title="Intelligence" subtitle="Optional LLM-powered enhancements. Each adds latency + token cost.">
          <Toggle label="LLM Topic Classification" value={config.use_llm_classification} onChange={(v) => update("use_llm_classification", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">When on, the LLM picks the topic for each timeline post. When off, fast keyword matcher runs instead.</p>
          <Toggle label="Vision Image Check" value={config.use_vision_image_check} onChange={(v) => update("use_vision_image_check", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Use vision model to verify source images are relevant before reposting media. Slow.</p>
          <Toggle label="Position Memory" value={config.position_memory_enabled} onChange={(v) => update("position_memory_enabled", v)} />
          <p className="text-[10px] text-neutral-600 ml-[172px] -mt-1">Track stances you've taken so future posts stay consistent.</p>
        </Section>

        {/* 9. LLM — credentials, set once */}
        <Section title="LLM" subtitle="Credentials and model choice. Usually set once.">
          <Select label="Provider" value={config.llm_provider} onChange={(v) => update("llm_provider", v)}
            options={["openai", "anthropic"]} />
          <Field label="OpenAI API Key" value={config.openai_api_key} onChange={(v) => update("openai_api_key", v)} type="password" />
          <Field label="Anthropic API Key" value={config.anthropic_api_key} onChange={(v) => update("anthropic_api_key", v)} type="password" />
          <Field label="OpenAI Model" value={config.openai_model} onChange={(v) => update("openai_model", v)} />
          <Field label="Anthropic Model" value={config.anthropic_model} onChange={(v) => update("anthropic_model", v)} />
        </Section>

        {/* 10. MODE-SPECIFIC */}
        {mode === "rt_farm" && (
          <Section title="RT Farm" subtitle="Bulk-retweet a target account's recent posts.">
            <Field label="Target Handle" value={config.rt_farm_target_handle} onChange={(v) => update("rt_farm_target_handle", v)} />
            <Number label="Delay (seconds)" value={config.rt_farm_delay_seconds} onChange={(v) => update("rt_farm_delay_seconds", v)} />
            <Number label="Max Scrolls" value={config.rt_farm_max_scrolls} onChange={(v) => update("rt_farm_max_scrolls", v)} />
          </Section>
        )}

        {mode === "sniper" && (
          <Section title="Sniper" subtitle="Reply to fast-trending posts before they peak.">
            <Toggle label="Enabled" value={config.sniper_enabled} onChange={(v) => update("sniper_enabled", v)} />
            <Number label="Scan Interval (min)" value={config.sniper_scan_interval_minutes} onChange={(v) => update("sniper_scan_interval_minutes", v)} />
            <Number label="Min Velocity (likes/min)" value={config.sniper_min_velocity} onChange={(v) => update("sniper_min_velocity", v)} />
            <Number label="Max Replies on Post" value={config.sniper_max_replies} onChange={(v) => update("sniper_max_replies", v)} />
            <Number label="Replies per Scan" value={config.sniper_replies_per_scan} onChange={(v) => update("sniper_replies_per_scan", v)} />
          </Section>
        )}
      </div>

      <div className="sticky bottom-0 bg-black/80 backdrop-blur-sm border-t border-neutral-800 py-4 -mx-6 px-6 mt-8 flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="bg-white text-black font-medium rounded-lg px-6 py-2 text-sm hover:bg-neutral-200 transition-colors disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Changes"}
        </button>
        {saved && <span className="text-green-400 text-sm">Saved</span>}
        {saveError && <span className="text-red-400 text-sm">Save failed: {saveError}</span>}
      </div>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5">
      <h3 className="text-sm font-medium text-white mb-1">{title}</h3>
      {subtitle && <p className="text-xs text-neutral-500 mb-4">{subtitle}</p>}
      {!subtitle && <div className="mb-1" />}
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs text-neutral-400 w-40 shrink-0">{label}</label>
      <input type={type} value={value || ""} onChange={(e) => onChange(e.target.value)}
        className="flex-1 bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500" />
    </div>
  );
}

function TextArea({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-xs text-neutral-400 block mb-1">{label}</label>
      <textarea value={value || ""} onChange={(e) => onChange(e.target.value)} rows={3}
        className="w-full bg-neutral-800 border border-neutral-700 rounded-md px-3 py-2 text-sm text-white outline-none focus:border-neutral-500 resize-y" />
    </div>
  );
}

function Number({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  const display = value === undefined || value === null ? "" : String(value);
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs text-neutral-400 w-40 shrink-0">{label}</label>
      <input
        type="number"
        min={0}
        value={display}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(0);
            return;
          }
          const parsed = parseInt(raw, 10);
          if (isNaN(parsed)) return;
          onChange(parsed < 0 ? 0 : parsed);
        }}
        className="w-24 bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500 text-center"
      />
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs text-neutral-400 w-40 shrink-0">{label}</label>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}
        className="bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

function DerivedTotals({ config }: { config: any }) {
  // Read-only summary so the user can see what their per-sequence numbers
  // mean for the day. Daily caps shown here are the runtime safety ceiling
  // computed by the backend (refreshed on save).
  const perSeq =
    (config.seq_text_tweets ?? 0) +
    (config.seq_rephrase_tweets ?? 0) +
    (config.seq_media_tweets ?? 0) +
    (config.seq_qrts ?? 0) +
    (config.seq_rts ?? 0) +
    (config.seq_comments ?? 0) +
    (config.seq_follows ?? 0) +
    (config.seq_threads ?? 0);
  return (
    <div className="mt-2 pt-3 border-t border-neutral-800 text-[11px] text-neutral-500 space-y-0.5">
      <div>Per sequence: <span className="text-neutral-300">{perSeq} actions</span></div>
      <div>
        Daily ceiling: {config.daily_max_tweets ?? 0} tweets · {config.daily_max_comments ?? 0} comments · {config.daily_max_qrts ?? 0} qrts · {config.daily_max_rts ?? 0} rts · {config.daily_max_follows ?? 0} follows
      </div>
    </div>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs text-neutral-400 w-40 shrink-0">{label}</label>
      <button onClick={() => onChange(!value)}
        className={`w-10 h-5 rounded-full transition-colors relative ${value ? "bg-green-500" : "bg-neutral-700"}`}>
        <div className={`w-4 h-4 bg-white rounded-full absolute top-0.5 transition-all ${value ? "left-[22px]" : "left-0.5"}`} />
      </button>
    </div>
  );
}

function Slider({ label, sublabel, value, onChange }: { label: string; sublabel: string; value: number; onChange: (v: number) => void }) {
  const v = value ?? 5;
  return (
    <div className="flex items-center gap-3">
      <div className="w-28 shrink-0">
        <label className="text-xs text-white font-medium">{label}</label>
        <div className="text-[10px] text-neutral-500">{sublabel}</div>
      </div>
      <input
        type="range"
        min={0}
        max={10}
        value={v}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="flex-1 h-1.5 accent-white bg-neutral-700 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
      />
      <span className="text-xs text-neutral-300 w-6 text-center font-mono">{v}</span>
    </div>
  );
}

const TOPICS_GENERAL = [
  "Database / backend", "Frontend / UI / UX", "DevOps / infra",
  "AI / ML tools", "Open source", "Startup / founder life",
  "Career / growth", "Developer tools / productivity", "Product thinking",
  "Hardware / gadgets", "Remote work / async", "Side projects",
  "Security / privacy", "Technical debt / refactoring", "Pricing / monetization",
  "API design", "Mobile / cross-platform", "Data / analytics",
  "Community / content creation", "Entrepreneurship", "Economics",
  "AI / future of AI", "Philosophy of tech", "AI agents",
  "Robotics / physical tech", "Current events / news", "Culture / memes / takes",
];

const TOPICS_DEGEN = [
  "BTC / Bitcoin", "ETH / Ethereum", "Solana / SOL",
  "Meme coins", "DeFi", "NFTs",
  "Market analysis", "Airdrops / Farming", "Layer 2s",
  "Crypto news", "Trading / Charts", "Regulation / Policy",
];

function TopicsPicker({ value, onChange, preset }: {
  value: Record<string, number>;
  onChange: (v: Record<string, number>) => void;
  preset: string[];
}) {
  const [customTopic, setCustomTopic] = useState("");
  const [showMore, setShowMore] = useState(false);

  const enabledTopics = Object.keys(value);
  const availablePresets = preset.filter((t) => value[t] === undefined);

  function addTopic(topic: string) {
    onChange({ ...value, [topic]: 3 });
  }

  function removeTopic(topic: string) {
    const copy = { ...value };
    delete copy[topic];
    onChange(copy);
  }

  function setWeight(topic: string, w: number) {
    onChange({ ...value, [topic]: Math.max(1, Math.min(5, w)) });
  }

  function addCustom() {
    const t = customTopic.trim();
    if (!t || value[t] !== undefined) return;
    onChange({ ...value, [t]: 3 });
    setCustomTopic("");
  }

  return (
    <div>
      {enabledTopics.length === 0 && (
        <p className="text-xs text-neutral-500 mb-3">No topics selected. Add topics below.</p>
      )}

      <div className="space-y-1.5 mb-4">
        {enabledTopics.map((topic) => (
          <div
            key={topic}
            className="flex items-center gap-2 rounded-lg px-3 py-1.5 bg-neutral-800/80 border border-neutral-700"
          >
            <span className="text-sm flex-1 truncate text-white">{topic}</span>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => setWeight(topic, n)}
                  className={`w-5 h-5 rounded text-[10px] font-mono transition-colors ${
                    n <= (value[topic] ?? 3)
                      ? "bg-white text-black"
                      : "bg-neutral-700 text-neutral-500 hover:bg-neutral-600"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <button
              onClick={() => removeTopic(topic)}
              className="ml-2 px-2 py-0.5 rounded text-xs text-red-400 border border-red-400/30 hover:bg-red-400/20 hover:border-red-400/60 transition-colors shrink-0"
              title="Remove topic"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {availablePresets.length > 0 && (
        <div className="mb-3">
          <button
            onClick={() => setShowMore(!showMore)}
            className="text-xs text-neutral-400 hover:text-white transition-colors flex items-center gap-1"
          >
            <span className="text-[10px]">{showMore ? "▼" : "▶"}</span>
            {showMore ? "Hide preset topics" : `Add from presets (${availablePresets.length})`}
          </button>
          {showMore && (
            <div className="mt-2 space-y-1">
              {availablePresets.map((topic) => (
                <button
                  key={topic}
                  onClick={() => addTopic(topic)}
                  className="w-full text-left flex items-center gap-2 rounded-lg px-3 py-1.5 bg-neutral-900/40 border border-neutral-800/50 opacity-60 hover:opacity-100 hover:border-neutral-600 transition-all"
                >
                  <span className="w-4 h-4 rounded border border-neutral-600 flex items-center justify-center shrink-0">
                    <span className="text-[10px] text-neutral-500">+</span>
                  </span>
                  <span className="text-sm text-neutral-400">{topic}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <input
          value={customTopic}
          onChange={(e) => setCustomTopic(e.target.value)}
          placeholder="Add custom topic..."
          onKeyDown={(e) => e.key === "Enter" && addCustom()}
          className="flex-1 bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500"
        />
        <button onClick={addCustom} className="bg-neutral-700 text-white text-xs font-medium px-3 py-1.5 rounded-md hover:bg-neutral-600">Add</button>
      </div>
    </div>
  );
}
