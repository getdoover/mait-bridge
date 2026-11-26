import "./styles.css";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";
import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";
import { useAgentChannel, useDooverClient, useMultiAgentAggregates } from "doover-js/react";

import { Button, Card, Dot, Message, SiteLink, Spinner } from "./components/ui";
import { fmtAgo, fmtClock } from "./lib/format";
import {
  CONVERSIONS,
  buildCatalogue,
  checkRows,
  cleanRows,
  emptyLink,
  findApp,
  findDevice,
  isLink,
  isSaved,
  linkPaths,
  modulesOf,
  refreshPaths,
  rowsFromLegacy,
  takesLink,
  toDoc,
  unwired,
  withLinkRows,
  type ChannelRow,
  type DeviceEntry,
  type Dict,
  type LinkRow,
  type Problem,
  type Row,
} from "./lib/map";

interface WidgetProps {
  uiElement?: { app_key?: string };
}

interface DeploymentConfig {
  applications?: Record<string, Dict & { DEVICE_MAP?: Record<string, { name?: string; display_name?: string }> }>;
}

const STALE_MIN = 120;

function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

const str = (v: unknown, d: string) => (typeof v === "string" && v.trim() ? v.trim() : d);

const FIELD =
  "h-8 w-full min-w-0 rounded-md border border-solid border-border bg-background px-2 text-[13px] text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";


function MapInner({ uiElement }: WidgetProps) {
  const params = useRemoteParams();
  const agentId = params?.agentId == null ? undefined : String(params.agentId);
  const appKey = uiElement?.app_key;
  const client = useDooverClient();
  const now = useNow();

  // The bridge's own config: which devices it may write to, its channels and subscriptions.
  const { data: deployment, isLoading } = useAgentChannel<DeploymentConfig>(agentId, "deployment_config");
  const bridgeCfg = appKey ? deployment?.applications?.[appKey] : undefined;
  const mapChannel = str(bridgeCfg?.map_channel, "mait_map");
  const stateChannel = str(bridgeCfg?.state_channel, "io_state");
  const commandChannel = str(bridgeCfg?.command_channel, "io_commands");
  const subscriptions = useMemo(
    () => (Array.isArray(bridgeCfg?.dv_proc_subscriptions) ? (bridgeCfg!.dv_proc_subscriptions as unknown[]).map(String) : []),
    [bridgeCfg],
  );
  const deviceMap = bridgeCfg?.DEVICE_MAP ?? {};
  const deviceIds = useMemo(() => Object.keys(deviceMap).filter((id) => id !== agentId), [deviceMap, agentId]);

  // Every device's apps (deployment_config) and the inputs they list (io_points tags).
  const deployments = useMultiAgentAggregates<Dict>("deployment_config", deviceIds, { fields: ["applications"] });
  const appKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const agg of Object.values(deployments.aggregatesByAgent)) {
      const apps = (agg?.data as Dict | undefined)?.applications;
      if (apps && typeof apps === "object") Object.keys(apps).forEach((k) => keys.add(k));
    }
    return [...keys].sort();
  }, [deployments.aggregatesByAgent]);
  const tags = useMultiAgentAggregates<Dict>("tag_values", appKeys.length ? deviceIds : [], { fields: appKeys });

  const catalogue = useMemo(() => {
    const deps: Record<string, unknown> = {};
    const tv: Record<string, unknown> = {};
    for (const id of deviceIds) {
      deps[id] = deployments.aggregatesByAgent[id]?.data;
      tv[id] = tags.aggregatesByAgent[id]?.data;
    }
    return buildCatalogue(deviceMap, deps, tv, agentId, stateChannel);
  }, [deviceIds, deviceMap, deployments.aggregatesByAgent, tags.aggregatesByAgent, agentId, stateChannel]);

  // The saved map, and the bridge's tags (when each module was last heard).
  const saved = useAgentChannel<Dict>(agentId, mapChannel);
  const ownTags = useAgentChannel<Record<string, Dict>>(agentId, "tag_values");
  const bridgeTags = (appKey && ownTags.data?.[appKey]) || {};

  const savedDoc = isSaved(saved.data) ? saved.data : undefined;
  const legacy = !savedDoc && Array.isArray(bridgeCfg?.modules) && (bridgeCfg!.modules as unknown[]).length > 0;
  const catalogueReady = deviceIds.length === 0 || Object.keys(deployments.aggregatesByAgent).length > 0;

  // The draft the page edits. It follows the saved map until edited.
  const [rows, setRows] = useState<Row[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const baseline = useMemo(() => {
    if (savedDoc) return withLinkRows(cleanRows(savedDoc.rows));
    if (legacy && catalogueReady) return withLinkRows(rowsFromLegacy(bridgeCfg?.modules, catalogue, stateChannel));
    return [];
  }, [savedDoc, legacy, catalogueReady, bridgeCfg, catalogue, stateChannel]);
  useEffect(() => {
    if (!dirty) setRows(baseline);
  }, [baseline, dirty]);

  const edit = useCallback((fn: (rows: Row[]) => Row[]) => {
    setRows((r) => withLinkRows(fn(r ?? [])));
    setDirty(true);
  }, []);

  const current = rows ?? [];
  const problems = useMemo(() => checkRows(current, catalogue, subscriptions, commandChannel), [current, catalogue, subscriptions, commandChannel]);
  const rowProblems = (i: number) => problems.filter((p) => p.row === i);
  const pageProblems = problems.filter((p) => p.row === -1);
  const errorCount = problems.filter((p) => p.level === "error").length;
  const notWired = useMemo(() => unwired(current, catalogue), [current, catalogue]);

  const me = useQuery({ queryKey: ["mait_map", "me"], queryFn: () => client.users.getMe(), staleTime: Infinity, retry: 1 });
  const actor = useMemo(() => {
    const u = me.data as Dict | undefined;
    if (!u) return undefined;
    const full = [u.first_name, u.last_name].filter((x) => typeof x === "string" && x).join(" ");
    return full || String(u.username ?? u.email ?? u.id ?? "");
  }, [me.data]);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const save = async () => {
    if (!agentId) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      const doc = toDoc(refreshPaths(current, catalogue), actor, Date.now());
      await client.aggregates.putAggregate(agentId, mapChannel, doc as unknown as Record<string, unknown>);
      setRows(withLinkRows(cleanRows(doc.rows)));
      setDirty(false);
      await saved.refetch?.();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };
  const discard = () => {
    setDirty(false);
    setRows(baseline);
    setSaveError(undefined);
  };

  const [newModule, setNewModule] = useState("");
  const modules = modulesOf(current);
  const addModule = () => {
    const n = Number(newModule);
    if (!Number.isInteger(n) || n < 1) return;
    if (!modules.includes(n)) edit((r) => [...r, emptyLink(n), emptyChannel(n)]);
    setNewModule("");
  };

  if (!agentId || !appKey) return <Message>Open this on the bridge's device page.</Message>;
  if (isLoading || saved.isLoading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Spinner /> Loading the map…
      </div>
    );
  }

  const heard = (module: number) => {
    const v = bridgeTags[`m${module}_heard`];
    return typeof v === "number" ? v : undefined;
  };

  return (
    <div className="mait-map flex flex-col gap-4 text-foreground">
      <p className="m-0 text-sm text-muted-foreground">
        Each row sends one radio module channel to one input of an app on a device. Pick the device, then the input; the apps on that device list
        what they take. Controls (pumps, valves, pivots) are mapped the same way, and their commands go back out on the same channel.
      </p>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm">
          <strong>{modules.length}</strong> modules · <strong>{new Set(current.map((r) => r.device).filter(Boolean)).size}</strong> devices
        </span>
        <span className="text-xs text-muted-foreground">
          {dirty
            ? "Unsaved changes"
            : savedDoc?.updated_at
              ? `Saved ${fmtClock(savedDoc.updated_at, now)}${savedDoc.updated_by ? ` by ${savedDoc.updated_by}` : ""}`
              : legacy
                ? "Not saved yet: the bridge is using the old Module Map from its config, shown here"
                : "Not saved yet"}
        </span>
        <span className="ml-auto flex items-center gap-2">
          {dirty && (
            <Button variant="ghost" size="sm" onClick={discard} disabled={saving}>
              Discard
            </Button>
          )}
          <Button variant="go" size="sm" onClick={save} disabled={saving || (!dirty && !legacy)} title={errorCount ? "Rows with problems are skipped by the bridge until fixed" : undefined}>
            {saving ? <Spinner /> : null}
            {errorCount ? `Save (${errorCount} to fix)` : "Save"}
          </Button>
        </span>
      </div>

      {saveError && <Notice level="error">Not saved: {saveError}</Notice>}
      {pageProblems.map((p, i) => (
        <Notice key={i} level={p.level}>
          {p.text}
        </Notice>
      ))}
      {!catalogueReady && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner /> Loading devices and their apps…
        </div>
      )}
      {catalogueReady && deviceIds.length === 0 && (
        <Notice level="warning">The bridge can't write to any devices yet. Give it the devices' group under Devices in its config.</Notice>
      )}

      {modules.map((module) => (
        <ModuleCard
          key={module}
          module={module}
          rows={current}
          catalogue={catalogue}
          heard={heard(module)}
          now={now}
          problems={rowProblems}
          onEdit={edit}
          modules={modules}
        />
      ))}

      <Card className="flex flex-wrap items-center gap-2 p-3">
        <span className="text-sm font-medium">Add a module</span>
        <input
          className={`${FIELD} !w-28`}
          type="number"
          min={1}
          placeholder="Number"
          value={newModule}
          onChange={(e) => setNewModule(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addModule()}
          aria-label="New module number"
        />
        <Button size="sm" onClick={addModule} disabled={!newModule}>
          Add
        </Button>
        {newModule && modules.includes(Number(newModule)) && <span className="text-xs text-muted-foreground">Module {newModule} is already in the map.</span>}
      </Card>

      {notWired.length > 0 && (
        <details className="rounded-xl border border-solid border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            Inputs with nothing mapped to them <span className="text-muted-foreground">({notWired.length})</span>
          </summary>
          <div className="mt-2 flex flex-col gap-1.5">
            {groupBy(notWired, (u) => u.device.id).map(([, items]) => (
              <div key={items[0].device.id} className="text-[13px]">
                <SiteLink to={`/agent/${items[0].device.id}`} className="font-medium text-foreground no-underline hover:underline">
                  {items[0].device.name}
                </SiteLink>
                <span className="text-muted-foreground">: {items.map((u) => `${u.app.name} · ${u.point.label}`).join(", ")}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function emptyChannel(module: number, device = ""): ChannelRow {
  return { module, channel: null, device, app_key: "", point: "", path: "" };
}

function groupBy<T>(xs: T[], key: (x: T) => string): Array<[string, T[]]> {
  const out = new Map<string, T[]>();
  for (const x of xs) {
    const k = key(x);
    out.set(k, [...(out.get(k) ?? []), x]);
  }
  return [...out.entries()];
}

function Notice({ level, children }: { level: "error" | "warning"; children: React.ReactNode }) {
  const colour = level === "error" ? "var(--color-halt)" : "#d97706";
  return (
    <div className="rounded-md px-3 py-2 text-[13px]" style={{ color: colour, background: `color-mix(in oklab, ${colour} 10%, transparent)` }}>
      {children}
    </div>
  );
}

function ModuleCard({
  module,
  rows,
  catalogue,
  heard,
  now,
  problems,
  onEdit,
  modules,
}: {
  module: number;
  rows: Row[];
  catalogue: DeviceEntry[];
  heard: number | undefined;
  now: number;
  problems: (i: number) => Problem[];
  onEdit: (fn: (rows: Row[]) => Row[]) => void;
  modules: number[];
}) {
  const mine = rows.map((r, i) => [r, i] as const).filter(([r]) => r.module === module);
  const devices = [...new Set(mine.map(([r]) => r.device).filter(Boolean))].map((d) => findDevice(catalogue, d)?.name ?? d);
  const channelRows = mine.filter(([r]) => !isLink(r));
  const lastDevice = channelRows.length ? channelRows[channelRows.length - 1][0].device : mine.find(([r]) => isLink(r))?.[0].device ?? "";
  const stale = heard != null && now - heard > STALE_MIN * 60_000;
  const [number, setNumber] = useState(String(module));
  useEffect(() => setNumber(String(module)), [module]);

  const renumber = () => {
    const n = Number(number);
    if (!Number.isInteger(n) || n < 1 || n === module || modules.includes(n)) {
      setNumber(String(module));
      return;
    }
    onEdit((rs) => rs.map((r) => (r.module === module ? { ...r, module: n } : r)));
  };
  const update = (i: number, patch: Partial<ChannelRow> | Partial<LinkRow>) =>
    onEdit((rs) => rs.map((r, j) => (j === i ? ({ ...r, ...patch } as Row) : r)));
  const remove = (i: number) => onEdit((rs) => rs.filter((_, j) => j !== i));
  const insertAfterModule = (row: Row) =>
    onEdit((rs) => {
      const last = rs.map((r) => r.module).lastIndexOf(module);
      return [...rs.slice(0, last + 1), row, ...rs.slice(last + 1)];
    });

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <label className="flex items-center gap-1.5 text-sm font-semibold">
          Module
          <input
            className={`${FIELD} !h-7 !w-20 font-semibold`}
            type="number"
            min={1}
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            onBlur={renumber}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            aria-label="Module number"
          />
        </label>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Dot colour={heard == null ? "#9ca3af" : stale ? "#d97706" : "var(--color-run)"} />
          {heard == null ? "Not heard yet" : `Heard ${fmtAgo(heard, now)}`}
        </span>
        {devices.length > 0 && <span className="truncate text-xs text-muted-foreground">→ {devices.join(", ")}</span>}
        <span className="ml-auto flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => insertAfterModule(emptyChannel(module, lastDevice))}>
            Add channel
          </Button>
          <Button size="sm" variant="stop" onClick={() => onEdit((rs) => rs.filter((r) => r.module !== module))} title={`Remove module ${module} and all its rows`}>
            Remove module
          </Button>
        </span>
      </div>
      <div>
        <div
          className="mait-row mait-head px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
          style={{ borderStyle: "solid", borderColor: "var(--border)", borderWidth: "1px 0 0 0" }}
        >
          <span className="mait-rm" />
          <span className="mait-ch">Channel</span>
          <span className="mait-dev">Device</span>
          <span className="mait-to">Goes to</span>
          <span className="mait-sc">Scaling</span>
        </div>
        {mine.map(([row, i]) =>
          isLink(row) ? (
            <LinkRowEditor key={i} row={row} catalogue={catalogue} problems={problems(i)} onChange={(p) => update(i, p)} />
          ) : (
              <ChannelRowEditor
                key={i}
                row={row}
                index={i}
                rows={rows}
                catalogue={catalogue}
                problems={problems(i)}
                onChange={(p) => update(i, p)}
              onRemove={() => remove(i)}
            />
          ),
        )}
        {channelRows.length === 0 && <div className="px-3 pb-3 text-xs text-muted-foreground">No channels yet.</div>}
      </div>
    </Card>
  );
}

function RowShell({ children, problems, extra }: { children: React.ReactNode; problems: Problem[]; extra?: React.ReactNode }) {
  return (
    <div className="px-3 py-2" style={{ borderStyle: "solid", borderColor: "var(--border)", borderWidth: "1px 0 0 0" }}>
      <div className="mait-row">
        {children}
      </div>
      {extra}
      {problems.map((p, k) => (
        <div key={k} className="mt-1 text-xs" style={{ color: p.level === "error" ? "var(--color-halt)" : "#d97706" }}>
          {p.text}
        </div>
      ))}
    </div>
  );
}

function DeviceSelect({
  value,
  catalogue,
  onChange,
  blank = "Choose a device…",
}: {
  value: string;
  catalogue: DeviceEntry[];
  onChange: (id: string) => void;
  blank?: string;
}) {
  const known = !value || catalogue.some((d) => d.id === value);
  return (
    <select className={`${FIELD} mait-dev`} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Device">
      <option value="">{blank}</option>
      {!known && <option value={value}>Unknown device {value}</option>}
      {catalogue.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
        </option>
      ))}
    </select>
  );
}

const RemoveButton = ({ onClick, label }: { onClick: () => void; label: string }) => (
  <Button variant="stop" size="sm" onClick={onClick} title={label} className="mait-rm !w-8 !px-0">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
    <span className="sr-only">{label}</span>
  </Button>
);

function ChannelRowEditor({
  row,
  index,
  rows,
  catalogue,
  problems,
  onChange,
  onRemove,
}: {
  row: ChannelRow;
  index: number;
  rows: Row[];
  catalogue: DeviceEntry[];
  problems: Problem[];
  onChange: (p: Partial<ChannelRow>) => void;
  onRemove: () => void;
}) {
  const device = findDevice(catalogue, row.device);
  const [scaling, setScaling] = useState(false);
  const value = row.app_key && row.point ? `${row.app_key}::${row.point}` : "";
  const fedBy = (appKey: string, point: string) => {
    const j = rows.findIndex((r, k) => k !== index && !isLink(r) && r.device === row.device && r.app_key === appKey && r.point === point);
    return j >= 0 ? (rows[j] as ChannelRow) : undefined;
  };
  const known = !value || device?.apps.some((a) => a.appKey === row.app_key && a.points.some((p) => p.id === row.point));
  const scaled = (row.multiplier ?? 1) !== 1 || (row.offset ?? 0) !== 0 || (row.conversion && row.conversion !== "None");

  return (
    <RowShell
      problems={problems}
      extra={
        scaling && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <label className="flex items-center gap-1.5">
              Multiply by
              <input className={`${FIELD} !w-24`} type="number" step="any" value={row.multiplier ?? 1} onChange={(e) => onChange({ multiplier: e.target.value === "" ? 1 : Number(e.target.value) })} />
            </label>
            <label className="flex items-center gap-1.5">
              then add
              <input className={`${FIELD} !w-24`} type="number" step="any" value={row.offset ?? 0} onChange={(e) => onChange({ offset: e.target.value === "" ? 0 : Number(e.target.value) })} />
            </label>
            <label className="flex items-center gap-1.5">
              Convert
              <select className={`${FIELD} !w-52`} value={row.conversion ?? "None"} onChange={(e) => onChange({ conversion: e.target.value })}>
                {CONVERSIONS.map((c) => (
                  <option key={c} value={c}>
                    {c === "None" ? "No conversion" : "GPS time of day (UTC hhmmss) to a timestamp"}
                  </option>
                ))}
              </select>
            </label>
            <span>Most inputs take the raw value; the app does its own scaling.</span>
          </div>
        )
      }
    >
      <RemoveButton onClick={onRemove} label={`Remove channel ${row.channel ?? ""}`.trim()} />
      <input
        className={`${FIELD} mait-ch`}
        type="number"
        min={1}
        value={row.channel ?? ""}
        onChange={(e) => onChange({ channel: e.target.value === "" ? null : Number(e.target.value) })}
        aria-label="Channel"
      />
      <DeviceSelect value={row.device} catalogue={catalogue} onChange={(id) => onChange({ device: id, app_key: "", point: "", path: "" })} />
      <select
        className={`${FIELD} mait-to`}
        value={value}
        disabled={!device}
        aria-label="Goes to"
        onChange={(e) => {
          const [appKey, point] = e.target.value.split("::");
          const p = findApp(catalogue, row.device, appKey)?.points.find((x) => x.id === point);
          onChange({ app_key: appKey ?? "", point: point ?? "", path: p?.path ?? "" });
        }}
      >
        <option value="">{device ? (device.apps.length ? "Choose an input…" : "No apps on this device take inputs") : "Choose a device first"}</option>
        {!known && <option value={value}>{row.point} (no longer on this device)</option>}
        {device?.apps.map((app) => (
          <optgroup key={app.appKey} label={app.name}>
            {app.points.map((p) => {
              const other = fedBy(app.appKey, p.id);
              return (
                <option key={p.id} value={`${app.appKey}::${p.id}`}>
                  {p.label}
                  {p.kind === "output" ? " (control)" : ""}
                  {other ? ` — already fed by ${other.module}.${other.channel ?? "?"}` : ""}
                </option>
              );
            })}
          </optgroup>
        ))}
      </select>
      <button
        type="button"
        onClick={() => setScaling((s) => !s)}
        className="mait-sc h-8 cursor-pointer truncate rounded-md border-0 bg-transparent px-1 text-left text-xs text-muted-foreground hover:text-foreground"
        title="Scaling and conversion"
      >
        {scaled ? scaleText(row) : "Raw"} {scaling ? "▴" : "▾"}
      </button>
    </RowShell>
  );
}

function scaleText(row: ChannelRow) {
  if (row.conversion && row.conversion !== "None") return "GPS time";
  const parts = [];
  if ((row.multiplier ?? 1) !== 1) parts.push(`×${row.multiplier}`);
  if ((row.offset ?? 0) !== 0) parts.push(`${(row.offset ?? 0) > 0 ? "+" : ""}${row.offset}`);
  return parts.join(" ");
}

function LinkRowEditor({
  row,
  catalogue,
  problems,
  onChange,
}: {
  row: LinkRow;
  catalogue: DeviceEntry[];
  problems: Problem[];
  onChange: (p: Partial<LinkRow>) => void;
}) {
  const device = findDevice(catalogue, row.device);
  const apps = device?.apps.filter(takesLink) ?? [];
  return (
    <RowShell problems={problems}>
      <span className="mait-rm" />
      <span className="mait-ch text-xs font-medium leading-tight text-muted-foreground" title="The module's one radio link: its link success, retries, route and last heard time">
        Radio link
      </span>
      <DeviceSelect
        value={row.device}
        catalogue={catalogue}
        blank="Not shown"
        onChange={(id) => {
          // A device with one link health app takes it straight away.
          const candidates = findDevice(catalogue, id)?.apps.filter(takesLink) ?? [];
          const only = candidates.length === 1 ? candidates[0] : undefined;
          onChange({ device: id, app_key: only?.appKey ?? "", paths: only ? linkPaths(only) : {} });
        }}
      />
      <select
        className={`${FIELD} mait-to`}
        value={row.app_key}
        disabled={!device}
        aria-label="Goes to"
        onChange={(e) => {
          const app = apps.find((a) => a.appKey === e.target.value);
          onChange({ app_key: e.target.value, paths: app ? linkPaths(app) : {} });
        }}
      >
        <option value="">{device ? (apps.length ? "Choose the app that shows it…" : "No link health app on this device") : "Not shown on any device"}</option>
        {row.app_key && !apps.some((a) => a.appKey === row.app_key) && <option value={row.app_key}>{row.app_key} (no longer on this device)</option>}
        {apps.map((a) => (
          <option key={a.appKey} value={a.appKey}>
            {a.name}
          </option>
        ))}
      </select>
      <span className="mait-sc" />
    </RowShell>
  );
}

const MaitMapWidget = (props: WidgetProps) => (
  <RemoteComponentWrapper>
    <MapInner {...props} />
  </RemoteComponentWrapper>
);

export default MaitMapWidget;
