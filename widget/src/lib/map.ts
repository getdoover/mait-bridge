// Pure logic of the mapping page: what can be mapped (each device's apps and
// their inputs), the saved map's rows, and what is wrong with them. No React,
// no I/O, so it can be tested with node --test.

export type Dict = Record<string, unknown>;

export const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);

// -- what an app offers -------------------------------------------------------

export interface Point {
  id: string;
  label: string;
  kind: "input" | "output";
  /** The message path the app reads, e.g. "$io_state.pump_control_1.pump_1". */
  path: string;
  /** Whether that is the app's automatic address (filled only by this map). */
  auto: boolean;
}

export interface AppEntry {
  appKey: string;
  name: string;
  /** "app": the app lists its own inputs. "config": found in its config. */
  source: "app" | "config";
  points: Point[];
}

export interface DeviceEntry {
  id: string;
  name: string;
  apps: AppEntry[];
}

/** The ids an app must offer for a module's radio link statistics to go to it. */
export const LINK_STATS = ["success_pct", "retries", "route", "last_heard"] as const;
export type LinkStat = (typeof LINK_STATS)[number];
export const LINK_POINTS: Record<LinkStat, string> = {
  success_pct: "link_success",
  retries: "retries",
  route: "route",
  last_heard: "last_heard",
};

/** Apps that are part of the device itself, never mapping targets. */
const SYSTEM_APPS = /^(doover_|platform_interface|host_configurator|mait_)/;

export function pointsFromTag(value: unknown): Point[] | undefined {
  const raw = isDict(value) && Array.isArray(value.points) ? value.points : Array.isArray(value) ? value : undefined;
  if (!raw) return undefined;
  const out: Point[] = [];
  for (const p of raw) {
    if (!isDict(p) || typeof p.id !== "string" || typeof p.path !== "string") continue;
    out.push({
      id: p.id,
      label: typeof p.label === "string" && p.label ? p.label : humanise(p.id),
      kind: p.kind === "output" ? "output" : "input",
      path: p.path,
      auto: p.auto === true,
    });
  }
  return out;
}

export function humanise(key: string): string {
  const words = key
    .replace(/_?(message_)?path$/, "")
    .replace(/_/g, " ")
    .trim();
  if (!words) return "Input";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Inputs found in an app's config: every string that is a path into the state channel. */
export function pointsFromConfig(config: unknown, stateChannel = "io_state"): Point[] {
  const out: Point[] = [];
  const prefix = `$${stateChannel}.`;
  const walk = (node: unknown, keyPath: string[], context: string) => {
    if (typeof node === "string") {
      if (!node.startsWith(prefix)) return;
      const key = keyPath[keyPath.length - 1] ?? "input";
      const label = [context, humanise(key)].filter(Boolean).join(" · ");
      out.push({ id: node.slice(prefix.length), label, kind: "input", path: node, auto: false });
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((child, i) => {
        const name = isDict(child) && typeof child.name === "string" ? child.name : `${humanise(keyPath[keyPath.length - 1] ?? "item")} ${i + 1}`;
        walk(child, [...keyPath, String(i)], name);
      });
      return;
    }
    if (isDict(node)) {
      for (const [k, v] of Object.entries(node)) {
        if (k.startsWith("dv_") || k === k.toUpperCase()) continue;
        walk(v, [...keyPath, k], context);
      }
    }
  };
  walk(config, [], "");
  // One point per path: two settings reading the same field are one input.
  const seen = new Set<string>();
  return out.filter((p) => (seen.has(p.path) ? false : (seen.add(p.path), true)));
}

export interface DeviceMapEntry {
  name?: string;
  display_name?: string;
}

/**
 * Every device the bridge may write to, with the apps on it that take inputs.
 * `deployments` is each device's deployment_config aggregate, `tags` its
 * tag_values aggregate.
 */
export function buildCatalogue(
  deviceMap: Record<string, DeviceMapEntry>,
  deployments: Record<string, unknown>,
  tags: Record<string, unknown>,
  selfId: string | undefined,
  stateChannel = "io_state",
): DeviceEntry[] {
  const devices: DeviceEntry[] = [];
  for (const [id, entry] of Object.entries(deviceMap)) {
    if (id === selfId) continue;
    const deployment = deployments[id];
    const apps = isDict(deployment) && isDict(deployment.applications) ? deployment.applications : {};
    const tagValues = isDict(tags[id]) ? (tags[id] as Dict) : {};
    const entries: AppEntry[] = [];
    for (const [appKey, cfg] of Object.entries(apps)) {
      if (!isDict(cfg)) continue;
      const appName = typeof cfg.APPLICATION_NAME === "string" ? cfg.APPLICATION_NAME : appKey;
      if (SYSTEM_APPS.test(appName)) continue;
      const fromTag = pointsFromTag(isDict(tagValues[appKey]) ? (tagValues[appKey] as Dict).io_points : undefined);
      const name = (typeof cfg.APP_INSTALL_DISPLAY_NAME === "string" && cfg.APP_INSTALL_DISPLAY_NAME) || (typeof cfg.APP_DISPLAY_NAME === "string" && cfg.APP_DISPLAY_NAME) || appKey;
      // A config path's setting is often just "Input": name it after the app instead.
      const points = fromTag ?? pointsFromConfig(cfg, stateChannel).map((p) => (p.label === "Input" ? { ...p, label: name } : p));
      if (!points.length) continue;
      entries.push({ appKey, name, source: fromTag ? "app" : "config", points });
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    devices.push({ id, name: entry.display_name || entry.name || `Device ${id}`, apps: entries });
  }
  devices.sort((a, b) => a.name.localeCompare(b.name));
  return devices;
}

export const findDevice = (cat: DeviceEntry[], id: string) => cat.find((d) => d.id === id);
export const findApp = (cat: DeviceEntry[], device: string, appKey: string) => findDevice(cat, device)?.apps.find((a) => a.appKey === appKey);
export const findPoint = (cat: DeviceEntry[], device: string, appKey: string, point: string) =>
  findApp(cat, device, appKey)?.points.find((p) => p.id === point);

/** Whether an app takes a module's radio link statistics (Link Health does). */
export const takesLink = (app: AppEntry) => LINK_STATS.some((s) => app.points.some((p) => p.id === LINK_POINTS[s]));

export function linkPaths(app: AppEntry): Partial<Record<LinkStat, string>> {
  const out: Partial<Record<LinkStat, string>> = {};
  for (const stat of LINK_STATS) {
    const p = app.points.find((x) => x.id === LINK_POINTS[stat]);
    if (p) out[stat] = p.path;
  }
  return out;
}

// -- the saved map ------------------------------------------------------------

export const CONVERSIONS = ["None", "UTC hhmmss to epoch ms"] as const;

export interface ChannelRow {
  module: number;
  channel: number | null;
  device: string;
  app_key: string;
  point: string;
  path: string;
  multiplier?: number;
  offset?: number;
  conversion?: string;
}

export interface LinkRow {
  module: number;
  link: true;
  device: string;
  app_key: string;
  paths: Partial<Record<LinkStat, string>>;
}

export type Row = ChannelRow | LinkRow;
export const isLink = (r: Row): r is LinkRow => (r as LinkRow).link === true;

export interface MapDoc {
  version: 1;
  rows: Row[];
  updated_at?: number;
  updated_by?: string;
}

export const isSaved = (doc: unknown): doc is MapDoc => isDict(doc) && Array.isArray(doc.rows);

export function cleanRows(raw: unknown): Row[] {
  if (!Array.isArray(raw)) return [];
  const out: Row[] = [];
  for (const r of raw) {
    if (!isDict(r) || typeof r.module !== "number") continue;
    if (r.link === true) {
      out.push({ module: r.module, link: true, device: String(r.device ?? ""), app_key: String(r.app_key ?? ""), paths: isDict(r.paths) ? (r.paths as LinkRow["paths"]) : {} });
    } else {
      out.push({
        module: r.module,
        channel: typeof r.channel === "number" ? r.channel : null,
        device: String(r.device ?? ""),
        app_key: String(r.app_key ?? ""),
        point: String(r.point ?? ""),
        path: String(r.path ?? ""),
        ...(typeof r.multiplier === "number" && r.multiplier !== 1 ? { multiplier: r.multiplier } : {}),
        ...(typeof r.offset === "number" && r.offset !== 0 ? { offset: r.offset } : {}),
        ...(typeof r.conversion === "string" && r.conversion !== "None" ? { conversion: r.conversion } : {}),
      });
    }
  }
  return out;
}

/** Module numbers in the map, ascending. */
export const modulesOf = (rows: Row[]) => [...new Set(rows.map((r) => r.module))].sort((a, b) => a - b);

/** Paths refreshed from what the apps publish now (an app's config may have changed). */
export function refreshPaths(rows: Row[], cat: DeviceEntry[]): Row[] {
  return rows.map((r) => {
    if (isLink(r)) {
      const app = findApp(cat, r.device, r.app_key);
      return app ? { ...r, paths: linkPaths(app) } : r;
    }
    const p = findPoint(cat, r.device, r.app_key, r.point);
    return p && p.path !== r.path ? { ...r, path: p.path } : r;
  });
}

// -- the old Module Map in config ---------------------------------------------

interface LegacyEntry {
  module?: number;
  device?: string;
  channels?: Array<{ channel?: number; field?: string; multiplier?: number; offset?: number; conversion?: string }>;
  include_link?: boolean;
  link_prefix?: string;
}

/** Rows for the old config map, pointing each field at the app input that reads it. */
export function rowsFromLegacy(modules: unknown, cat: DeviceEntry[], stateChannel = "io_state"): Row[] {
  if (!Array.isArray(modules)) return [];
  const rows: Row[] = [];
  const byPath = (device: string, path: string) => {
    for (const app of findDevice(cat, device)?.apps ?? []) {
      const p = app.points.find((x) => x.path === path);
      if (p) return { app, point: p };
    }
    return undefined;
  };
  for (const item of modules as unknown[]) {
    if (!isDict(item)) continue;
    const raw = item as LegacyEntry;
    if (typeof raw.module !== "number" || !raw.device) continue;
    const device = String(raw.device);
    for (const ch of Array.isArray(raw.channels) ? raw.channels : []) {
      if (typeof ch.channel !== "number" || !ch.field) continue;
      const path = `$${stateChannel}.${ch.field}`;
      const hit = byPath(device, path);
      rows.push({
        module: raw.module,
        channel: ch.channel,
        device,
        app_key: hit?.app.appKey ?? "",
        point: hit?.point.id ?? ch.field,
        path,
        ...(ch.multiplier != null && ch.multiplier !== 1 ? { multiplier: ch.multiplier } : {}),
        ...(ch.offset != null && ch.offset !== 0 ? { offset: ch.offset } : {}),
        ...(ch.conversion && ch.conversion !== "None" ? { conversion: ch.conversion } : {}),
      });
    }
    if (raw.include_link !== false) {
      const prefix = raw.link_prefix ?? "";
      const hit = byPath(device, `$${stateChannel}.${prefix}route`);
      if (hit) {
        rows.push({
          module: raw.module,
          link: true,
          device,
          app_key: hit.app.appKey,
          paths: {
            success_pct: `$${stateChannel}.${prefix}link_success_pct`,
            retries: `$${stateChannel}.${prefix}retries`,
            route: `$${stateChannel}.${prefix}route`,
            last_heard: `$${stateChannel}.${prefix}last_heard`,
          },
        });
      }
    }
  }
  return rows;
}

// -- problems -----------------------------------------------------------------

export interface Problem {
  /** Index of the row it is about, or -1 for the whole map. */
  row: number;
  text: string;
  /** Saving is still allowed (the bridge skips the row) but it needs fixing. */
  level: "error" | "warning";
}

export function checkRows(rows: Row[], cat: DeviceEntry[], subscriptions: string[], commandChannel = "io_commands"): Problem[] {
  const problems: Problem[] = [];
  const seenChannel = new Map<string, number>();
  const seenPath = new Map<string, number>();
  const seenLink = new Map<string, number>();
  const needCommands = new Set<string>();

  rows.forEach((r, i) => {
    const dev = findDevice(cat, r.device);
    if (isLink(r) && !r.device) {
      // The radio link isn't shown anywhere: allowed.
      if (seenLink.has(String(r.module))) problems.push({ row: i, text: `Module ${r.module} has more than one radio link row`, level: "error" });
      seenLink.set(String(r.module), i);
      return;
    }
    if (!r.device) {
      problems.push({ row: i, text: "Choose the device it goes to", level: "error" });
      return;
    }
    if (!dev) {
      problems.push({ row: i, text: "The bridge can't write to this device: it isn't in the bridge's devices", level: "error" });
      return;
    }
    if (isLink(r)) {
      const app = findApp(cat, r.device, r.app_key);
      if (!r.app_key) problems.push({ row: i, text: "Choose the app that shows the radio link, or set the device back to \"Not shown\"", level: "error" });
      else if (!app) problems.push({ row: i, text: "That app is no longer on this device", level: "error" });
      if (seenLink.has(String(r.module))) problems.push({ row: i, text: `Module ${r.module} has more than one radio link row`, level: "error" });
      seenLink.set(String(r.module), i);
      return;
    }
    if (r.channel == null) problems.push({ row: i, text: "Enter the channel number", level: "error" });
    if (!r.app_key || !r.point) {
      problems.push({ row: i, text: "Choose the input it feeds", level: "error" });
      return;
    }
    const point = findPoint(cat, r.device, r.app_key, r.point);
    if (!point) {
      problems.push({ row: i, text: "That input no longer exists on this device (its app was removed or changed)", level: "error" });
    } else if (point.kind === "output") {
      needCommands.add(r.device);
    }
    if (r.channel != null) {
      const ck = `${r.module}.${r.channel}|${r.device}`;
      if (seenChannel.has(ck)) problems.push({ row: i, text: `Channel ${r.module}.${r.channel} is mapped twice to ${dev.name}`, level: "error" });
      seenChannel.set(ck, i);
    }
    const pk = `${r.device}|${point?.path ?? r.path}`;
    if (seenPath.has(pk)) {
      const other = rows[seenPath.get(pk)!] as ChannelRow;
      problems.push({ row: i, text: `This input is already fed by channel ${other.module}.${other.channel}`, level: "error" });
    }
    seenPath.set(pk, i);
  });

  const subs = new Set(subscriptions);
  const missing = [...needCommands].filter((d) => !subs.has(`${d}-${commandChannel}`));
  if (missing.length) {
    const names = missing.map((d) => findDevice(cat, d)?.name ?? d).join(", ");
    problems.push({
      row: -1,
      level: "warning",
      text: `Controls on ${names} won't reach the radios yet: add "<device id>-${commandChannel}" for ${missing.length === 1 ? "it" : "them"} to the bridge's Subscriptions and redeploy it`,
    });
  }
  return problems;
}

/** Inputs on each device that no row feeds yet. */
export function unwired(rows: Row[], cat: DeviceEntry[]): Array<{ device: DeviceEntry; app: AppEntry; point: Point }> {
  const fed = new Set<string>();
  for (const r of rows) {
    if (isLink(r)) {
      for (const stat of LINK_STATS) fed.add(`${r.device}|${r.app_key}|${LINK_POINTS[stat]}`);
    } else fed.add(`${r.device}|${r.app_key}|${r.point}`);
  }
  const out: Array<{ device: DeviceEntry; app: AppEntry; point: Point }> = [];
  for (const device of cat) {
    for (const app of device.apps) {
      for (const point of app.points) {
        // Only automatic inputs depend on this map; an explicit path is fed from elsewhere.
        if (point.auto && !fed.has(`${device.id}|${app.appKey}|${point.id}`)) out.push({ device, app, point });
      }
    }
  }
  return out;
}

/** A module's one radio link row: every module has exactly one, first among its rows. */
export const emptyLink = (module: number): LinkRow => ({ module, link: true, device: "", app_key: "", paths: {} });

/**
 * Rows with every module's radio link row first among that module's rows. A
 * module without one gets an empty one ("not shown anywhere"); extra link rows
 * of a module (only possible in a map saved elsewhere) are kept, after the
 * first, so the page can flag them.
 */
export function withLinkRows(rows: Row[]): Row[] {
  const out: Row[] = [];
  const done = new Set<number>();
  for (const r of rows) {
    if (done.has(r.module)) continue;
    done.add(r.module);
    const mine = rows.filter((x) => x.module === r.module);
    const links = mine.filter(isLink);
    out.push(...(links.length ? links : [emptyLink(r.module)]), ...mine.filter((x) => !isLink(x)));
  }
  return out;
}

export function toDoc(rows: Row[], by: string | undefined, now: number): MapDoc {
  // A radio link that isn't shown anywhere is not saved.
  const kept = cleanRows(rows).filter((r) => !isLink(r) || (r.device && r.app_key));
  return { version: 1, rows: kept, updated_at: now, ...(by ? { updated_by: by } : {}) };
}
