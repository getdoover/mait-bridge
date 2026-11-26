import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildCatalogue,
  checkRows,
  humanise,
  pointsFromConfig,
  pointsFromTag,
  refreshPaths,
  rowsFromLegacy,
  toDoc,
  unwired,
  withLinkRows,
  type Row,
} from "../src/lib/map.ts";

const TANK = "248969125739677702";
const SELF = "249020530978490113";

const deviceMap = {
  [TANK]: { display_name: "Existing Tank 1" },
  [SELF]: { display_name: "Barmount Feedlot" },
};

const deployments = {
  [TANK]: {
    applications: {
      analog_level_sensor_processor_1: {
        APPLICATION_NAME: "analog_level_sensor_processor",
        APP_INSTALL_DISPLAY_NAME: "Tank Level",
        AGENT_ID: TANK,
        input_message_path: "$io_state.tank_level",
        dv_proc_subscriptions: ["io_state"],
      },
      valve_control_1: {
        APPLICATION_NAME: "valve_control",
        APP_INSTALL_DISPLAY_NAME: "Flood Gate",
        valves: [{ name: "Flood Gate 1", state_path: "", target: "flood_gate_1" }],
      },
      link_health_1: { APPLICATION_NAME: "link_health", APP_INSTALL_DISPLAY_NAME: "Link Health" },
      doover_device_agent_1: { APPLICATION_NAME: "doover_device_agent", x_path: "$io_state.nope" },
    },
  },
};

const tags = {
  [TANK]: {
    valve_control_1: {
      io_points: {
        version: 1,
        points: [
          { id: "flood_gate_1", label: "Flood Gate 1", kind: "output", path: "$io_state.valve_control_1.flood_gate_1", auto: true },
          { id: "flood_gate_1_position", label: "Flood Gate 1 position", kind: "input", path: "$io_state.valve_control_1.flood_gate_1_position", auto: true },
        ],
      },
    },
    link_health_1: {
      io_points: {
        version: 1,
        points: ["battery_voltage", "link_success", "retries", "route", "last_heard"].map((id) => ({
          id,
          label: humanise(id),
          kind: "input",
          path: `$io_state.link_health_1.${id}`,
          auto: true,
        })),
      },
    },
  },
};

const cat = buildCatalogue(deviceMap, deployments, tags, SELF);

test("catalogue: own device and system apps left out, tag wins over config", () => {
  assert.deepEqual(cat.map((d) => d.name), ["Existing Tank 1"]);
  // Sorted by install name: Flood Gate, Link Health, Tank Level.
  assert.deepEqual(cat[0].apps.map((a) => [a.appKey, a.source]), [
    ["valve_control_1", "app"],
    ["link_health_1", "app"],
    ["analog_level_sensor_processor_1", "config"],
  ]);
  const level = cat[0].apps.find((a) => a.appKey === "analog_level_sensor_processor_1")!;
  assert.deepEqual(level.points, [{ id: "tank_level", label: "Tank Level", kind: "input", path: "$io_state.tank_level", auto: false }]);
});

test("config scan labels array items by name", () => {
  const pts = pointsFromConfig({ valves: [{ name: "Gate A", state_path: "$io_state.a" }], other: "$io_state.a" });
  assert.deepEqual(pts.map((p) => p.label), ["Gate A · State"]);
  assert.equal(pointsFromTag(undefined), undefined);
  assert.deepEqual(pointsFromTag({ points: [{ id: "x", path: "$io_state.x" }, { bad: 1 }] })?.map((p) => p.label), ["X"]);
});

const rows: Row[] = [
  { module: 10, channel: 3, device: TANK, app_key: "analog_level_sensor_processor_1", point: "tank_level", path: "$io_state.tank_level" },
  { module: 10, channel: 1, device: TANK, app_key: "valve_control_1", point: "flood_gate_1", path: "$io_state.old" },
  { module: 10, link: true, device: TANK, app_key: "link_health_1", paths: {} },
];

test("refreshPaths takes the apps' current paths", () => {
  const fresh = refreshPaths(rows, cat);
  assert.equal((fresh[1] as { path: string }).path, "$io_state.valve_control_1.flood_gate_1");
  assert.deepEqual((fresh[2] as { paths: object }).paths, {
    success_pct: "$io_state.link_health_1.link_success",
    retries: "$io_state.link_health_1.retries",
    route: "$io_state.link_health_1.route",
    last_heard: "$io_state.link_health_1.last_heard",
  });
});

test("checkRows: missing subscription for outputs, duplicates, unknown device", () => {
  const problems = checkRows(
    [
      ...rows,
      { module: 20, channel: 3, device: TANK, app_key: "analog_level_sensor_processor_1", point: "tank_level", path: "$io_state.tank_level" },
      { module: 10, channel: 3, device: TANK, app_key: "", point: "", path: "" },
      { module: 30, channel: 1, device: "999", app_key: "x", point: "y", path: "" },
    ],
    cat,
    [],
  );
  assert.ok(problems.some((p) => p.row === 3 && /already fed by channel 10.3/.test(p.text)));
  assert.ok(problems.some((p) => p.row === 4 && /Choose the input/.test(p.text)));
  assert.ok(problems.some((p) => p.row === 5 && /can't write/.test(p.text)));
  assert.ok(problems.some((p) => p.row === -1 && p.level === "warning" && /Existing Tank 1/.test(p.text)));
  assert.equal(checkRows(rows, cat, [`${TANK}-io_commands`]).length, 0);
});

test("unwired lists automatic inputs nobody feeds", () => {
  const left = unwired(rows, cat).map((u) => u.point.id);
  assert.deepEqual(left, ["flood_gate_1_position", "battery_voltage"]);
});

test("rowsFromLegacy points old fields at the apps that read them", () => {
  const legacyCat = buildCatalogue(deviceMap, deployments, {}, SELF);
  const out = rowsFromLegacy([{ module: 10, device: TANK, channels: [{ channel: 3, field: "tank_level" }, { channel: 9, field: "spare" }] }], legacyCat);
  assert.deepEqual(out[0], { module: 10, channel: 3, device: TANK, app_key: "analog_level_sensor_processor_1", point: "tank_level", path: "$io_state.tank_level" });
  assert.equal((out[1] as { app_key: string }).app_key, "");
  assert.equal(out.length, 2);
});

test("toDoc drops default scaling", () => {
  const doc = toDoc([{ module: 1, channel: 2, device: TANK, app_key: "a", point: "b", path: "$io_state.a.b", multiplier: 1, offset: 0, conversion: "None" }], "Sid", 5);
  assert.deepEqual(doc, { version: 1, rows: [{ module: 1, channel: 2, device: TANK, app_key: "a", point: "b", path: "$io_state.a.b" }], updated_at: 5, updated_by: "Sid" });
});

test("every module has one radio link row, first; an unused one is not saved", () => {
  const out = withLinkRows([
    { module: 20, channel: 3, device: TANK, app_key: "a", point: "b", path: "$io_state.a.b" },
    { module: 10, channel: 1, device: TANK, app_key: "a", point: "c", path: "$io_state.a.c" },
    { module: 10, link: true, device: TANK, app_key: "link_health_1", paths: {} },
  ]);
  assert.deepEqual(out.map((r) => [r.module, "link" in r]), [[20, true], [20, false], [10, true], [10, false]]);
  assert.equal(checkRows(out, cat, [`${TANK}-io_commands`]).filter((p) => p.row === 0).length, 0);
  assert.deepEqual(toDoc(out, undefined, 1).rows.map((r) => r.module), [20, 10, 10]);
  const twice = checkRows([...out, { module: 10, link: true, device: "", app_key: "", paths: {} }], cat, []);
  assert.ok(twice.some((p) => /more than one radio link/.test(p.text)));
});
