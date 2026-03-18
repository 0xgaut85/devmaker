import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";

export default function Settings() {
  const { accountId } = useParams<{ accountId: string }>();
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
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
    try {
      await api.config.update(accountId, config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  }

  function update(key: string, value: any) {
    setConfig((c) => c ? { ...c, [key]: value } : c);
  }

  if (loadError) return <div className="text-red-400 text-sm">Error: {loadError}</div>;
  if (!config) return <div className="text-neutral-500 text-sm">Loading...</div>;

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <Link to="/accounts" className="text-neutral-500 hover:text-white text-sm">← Back</Link>
        <h2 className="text-xl font-semibold text-white">Settings</h2>
      </div>

      <div className="space-y-8">
        <Section title="Mode">
          <Select label="Farming Mode" value={config.farming_mode} onChange={(v) => update("farming_mode", v)}
            options={["dev", "project", "degen", "rt_farm", "sniper"]} />
        </Section>

        <Section title="LLM">
          <Select label="Provider" value={config.llm_provider} onChange={(v) => update("llm_provider", v)}
            options={["openai", "anthropic"]} />
          <Field label="OpenAI API Key" value={config.openai_api_key} onChange={(v) => update("openai_api_key", v)} type="password" />
          <Field label="Anthropic API Key" value={config.anthropic_api_key} onChange={(v) => update("anthropic_api_key", v)} type="password" />
          <Field label="OpenAI Model" value={config.openai_model} onChange={(v) => update("openai_model", v)} />
          <Field label="Anthropic Model" value={config.anthropic_model} onChange={(v) => update("anthropic_model", v)} />
        </Section>

        <Section title="Voice">
          <TextArea label="Voice Description" value={config.voice_description} onChange={(v) => update("voice_description", v)} />
          <TextArea label="Bad Examples" value={config.bad_examples} onChange={(v) => update("bad_examples", v)} />
          <TextArea label="Good Examples" value={config.good_examples} onChange={(v) => update("good_examples", v)} />
        </Section>

        <Section title="Topics">
          <p className="text-xs text-neutral-500 mb-3">Add topics with weights (higher = more frequent). Used for dev/project modes.</p>
          <TopicsEditor value={config.topics || {}} onChange={(v) => update("topics", v)} />
        </Section>

        <Section title="Degen Voice">
          <TextArea label="Degen Voice" value={config.degen_voice_description} onChange={(v) => update("degen_voice_description", v)} />
          <TextArea label="Do" value={config.degen_do} onChange={(v) => update("degen_do", v)} />
          <TextArea label="Don't" value={config.degen_dont} onChange={(v) => update("degen_dont", v)} />
        </Section>

        <Section title="Degen Topics">
          <p className="text-xs text-neutral-500 mb-3">Topics for degen farming mode.</p>
          <TopicsEditor value={config.degen_topics || {}} onChange={(v) => update("degen_topics", v)} />
        </Section>

        <Section title="Project Farming">
          <Field label="Project Name" value={config.project_name} onChange={(v) => update("project_name", v)} />
          <TextArea label="About" value={config.project_about} onChange={(v) => update("project_about", v)} />
          <TextArea label="Do" value={config.project_do} onChange={(v) => update("project_do", v)} />
          <TextArea label="Don't" value={config.project_dont} onChange={(v) => update("project_dont", v)} />
          <Number label="Comments per Sequence" value={config.project_timeline_comments} onChange={(v) => update("project_timeline_comments", v)} />
          <Number label="Min Likes" value={config.project_timeline_min_likes} onChange={(v) => update("project_timeline_min_likes", v)} />
        </Section>

        <Section title="RT Farm">
          <Field label="Target Handle" value={config.rt_farm_target_handle} onChange={(v) => update("rt_farm_target_handle", v)} />
          <Number label="Delay (seconds)" value={config.rt_farm_delay_seconds} onChange={(v) => update("rt_farm_delay_seconds", v)} />
          <Number label="Max Scrolls" value={config.rt_farm_max_scrolls} onChange={(v) => update("rt_farm_max_scrolls", v)} />
        </Section>

        <Section title="Sniper">
          <Toggle label="Enabled" value={config.sniper_enabled} onChange={(v) => update("sniper_enabled", v)} />
          <Number label="Scan Interval (min)" value={config.sniper_scan_interval_minutes} onChange={(v) => update("sniper_scan_interval_minutes", v)} />
          <Number label="Min Velocity" value={config.sniper_min_velocity} onChange={(v) => update("sniper_min_velocity", v)} />
          <Number label="Max Replies on Post" value={config.sniper_max_replies} onChange={(v) => update("sniper_max_replies", v)} />
          <Number label="Replies per Scan" value={config.sniper_replies_per_scan} onChange={(v) => update("sniper_replies_per_scan", v)} />
        </Section>

        <Section title="Intelligence">
          <Toggle label="LLM Classification" value={config.use_llm_classification} onChange={(v) => update("use_llm_classification", v)} />
          <Toggle label="Vision Image Check" value={config.use_vision_image_check} onChange={(v) => update("use_vision_image_check", v)} />
          <Toggle label="Position Memory" value={config.position_memory_enabled} onChange={(v) => update("position_memory_enabled", v)} />
        </Section>

        <Section title="Daily Caps">
          <Number label="Tweets" value={config.daily_max_tweets} onChange={(v) => update("daily_max_tweets", v)} />
          <Number label="Comments" value={config.daily_max_comments} onChange={(v) => update("daily_max_comments", v)} />
          <Number label="Likes" value={config.daily_max_likes} onChange={(v) => update("daily_max_likes", v)} />
          <Number label="Follows" value={config.daily_max_follows} onChange={(v) => update("daily_max_follows", v)} />
          <Number label="QRTs" value={config.daily_max_qrts} onChange={(v) => update("daily_max_qrts", v)} />
        </Section>

        <Section title="Active Hours">
          <Toggle label="Enabled" value={config.active_hours_enabled} onChange={(v) => update("active_hours_enabled", v)} />
          <Number label="Start Hour" value={config.active_hours_start} onChange={(v) => update("active_hours_start", v)} />
          <Number label="End Hour" value={config.active_hours_end} onChange={(v) => update("active_hours_end", v)} />
          <Field label="Timezone" value={config.active_hours_timezone} onChange={(v) => update("active_hours_timezone", v)} />
        </Section>

        <Section title="Timing">
          <Number label="Action Delay (s)" value={config.action_delay_seconds} onChange={(v) => update("action_delay_seconds", v)} />
          <Number label="Sequence Delay (min)" value={config.sequence_delay_minutes} onChange={(v) => update("sequence_delay_minutes", v)} />
          <Number label="Min Engagement Likes" value={config.min_engagement_likes} onChange={(v) => update("min_engagement_likes", v)} />
          <Number label="Thread Every N Sequences" value={config.thread_every_n_sequences} onChange={(v) => update("thread_every_n_sequences", v)} />
        </Section>
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
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5">
      <h3 className="text-sm font-medium text-white mb-4">{title}</h3>
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
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs text-neutral-400 w-40 shrink-0">{label}</label>
      <input type="number" value={value ?? 0} onChange={(e) => onChange(parseInt(e.target.value) || 0)}
        className="w-24 bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500 text-center" />
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

function TopicsEditor({ value, onChange }: { value: Record<string, number>; onChange: (v: Record<string, number>) => void }) {
  const [newTopic, setNewTopic] = useState("");
  const [newWeight, setNewWeight] = useState(1);

  function addTopic() {
    const t = newTopic.trim();
    if (!t) return;
    onChange({ ...value, [t]: newWeight });
    setNewTopic("");
    setNewWeight(1);
  }

  function removeTopic(key: string) {
    const copy = { ...value };
    delete copy[key];
    onChange(copy);
  }

  function updateWeight(key: string, w: number) {
    onChange({ ...value, [key]: w });
  }

  const entries = Object.entries(value);

  return (
    <div>
      {entries.length > 0 && (
        <div className="space-y-2 mb-3">
          {entries.map(([topic, weight]) => (
            <div key={topic} className="flex items-center gap-2">
              <span className="text-sm text-white flex-1 truncate">{topic}</span>
              <input
                type="number"
                min={1}
                max={10}
                value={weight}
                onChange={(e) => updateWeight(topic, parseInt(e.target.value) || 1)}
                className="w-16 bg-neutral-800 border border-neutral-700 rounded-md px-2 py-1 text-xs text-white text-center outline-none"
              />
              <button
                onClick={() => removeTopic(topic)}
                className="text-neutral-500 hover:text-red-400 text-xs px-2 py-1 rounded hover:bg-neutral-800"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
      {entries.length === 0 && (
        <p className="text-neutral-600 text-xs mb-3">No topics added yet.</p>
      )}
      <div className="flex items-center gap-2">
        <input
          value={newTopic}
          onChange={(e) => setNewTopic(e.target.value)}
          placeholder="Topic name"
          onKeyDown={(e) => e.key === "Enter" && addTopic()}
          className="flex-1 bg-neutral-800 border border-neutral-700 rounded-md px-3 py-1.5 text-sm text-white outline-none focus:border-neutral-500"
        />
        <input
          type="number"
          min={1}
          max={10}
          value={newWeight}
          onChange={(e) => setNewWeight(parseInt(e.target.value) || 1)}
          className="w-16 bg-neutral-800 border border-neutral-700 rounded-md px-2 py-1.5 text-sm text-white text-center outline-none"
          title="Weight"
        />
        <button
          onClick={addTopic}
          className="bg-neutral-700 text-white text-xs font-medium px-3 py-1.5 rounded-md hover:bg-neutral-600"
        >
          Add
        </button>
      </div>
    </div>
  );
}
