import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from pydoover.models import (
    AggregateUpdateEvent,
    ConnectionConfig,
    ConnectionDetermination,
    ConnectionStatus,
    ConnectionType,
    MessageCreateEvent,
)
from pydoover.processor import Application

from . import bridge
from .app_config import MaitBridgeCloudConfig, plain
from .app_tags import MaitBridgeCloudTags, module_heard_key, settings_fp_key
from .app_ui import MaitBridgeCloudUI

log = logging.getLogger(__name__)

USER_AGENT = "mait-bridge-cloud"
MAX_ERRORS_SHOWN = 4


def _now_ms() -> int:
    return int(time.time() * 1000)


def _num(element, default: float) -> float:
    value = getattr(element, "value", None) if element is not None else None
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _str(element, default: str) -> str:
    value = getattr(element, "value", None) if element is not None else None
    return value.strip() if isinstance(value, str) and value.strip() else default


def _short(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    if "403" in text or "ermission" in text or "Forbidden" in type(exc).__name__:
        return "permission denied"
    return text[:120]


class MaitBridgeCloudApplication(Application):
    config: MaitBridgeCloudConfig
    tags: MaitBridgeCloudTags
    ui: MaitBridgeCloudUI

    config_cls = MaitBridgeCloudConfig
    tags_cls = MaitBridgeCloudTags
    ui_cls = MaitBridgeCloudUI

    async def setup(self):
        # The connection ping would otherwise look up a public IP on every call.
        self.api.lookup_ip = False
        self.mappings, self.config_problems = bridge.parse_module_map(
            plain(self.config.modules)
        )
        self.module_index = bridge.by_module(self.mappings)
        self.devices = bridge.mapped_devices(self.mappings)
        c = self.config
        self.uplink_channel = _str(c.uplink_channel, "mait_uplink")
        self.downlink_channel = _str(c.downlink_channel, "mait_downlink")
        self.state_channel = _str(c.state_channel, "io_state")
        self.command_channel = _str(c.command_channel, "io_commands")
        self.settings_channel = _str(c.settings_channel, "control_settings")

    # -- events ---------------------------------------------------------------

    async def on_message_create(self, event: MessageCreateEvent):
        channel = event.channel
        data = event.message.data if event.message is not None else None
        if channel.agent_id == self.agent_id and channel.name == self.uplink_channel:
            await self.handle_uplink(data, _now_ms())
        elif (
            channel.name == self.command_channel
            and str(channel.agent_id) in self.devices
        ):
            await self.handle_command(str(channel.agent_id), data, _now_ms())

    async def on_aggregate_update(self, event: AggregateUpdateEvent):
        channel = event.channel
        if (
            channel.name == self.settings_channel
            and str(channel.agent_id) in self.devices
        ):
            data = getattr(event.aggregate, "data", None)
            await self.handle_settings(str(channel.agent_id), data, _now_ms())

    async def on_schedule(self, event):
        now = _now_ms()
        await self.reconcile_settings(now)
        await self.refresh_status(now)

    async def on_deployment(self, event):
        now = _now_ms()
        await self._set("devices_mapped", len(self.devices))
        await self._set(
            "config_errors", "; ".join(self.config_problems[:MAX_ERRORS_SHOWN])
        )
        await self.reconcile_settings(now)
        await self.refresh_status(now)

    # -- uplink ---------------------------------------------------------------

    async def handle_uplink(self, data: Any, now_ms: int):
        reports = bridge.uplink_reports(data)
        if not reports:
            log.info("Uplink without module reports ignored: %r", data)
            return

        errors: list[str] = []
        per_device: dict[str, list[tuple[bridge.ModuleMapping, dict, int]]] = {}
        for report in reports:
            module = int(report["module"])
            mapping = self.module_index.get(module)
            if mapping is None:
                errors.append(f"Module {module} is not in the module map")
                continue
            heard_ms = bridge._int(report.get("heard_ts")) or now_ms
            per_device.setdefault(mapping.device_id, []).append(
                (mapping, report, heard_ms)
            )

        results = await asyncio.gather(
            *(
                self._publish_device(device_id, items, now_ms)
                for device_id, items in per_device.items()
            )
        )
        for problems in results:
            errors.extend(problems)

        for items in per_device.values():
            for mapping, _, heard_ms in items:
                key = module_heard_key(mapping.module)
                if heard_ms > (self.get_tag(key) or 0):
                    await self.set_tag(key, heard_ms)

        await self._set("last_uplink", now_ms)
        await self._set("devices_mapped", len(self.devices))
        await self._set("uplink_errors", "; ".join(errors[:MAX_ERRORS_SHOWN]))
        await self.refresh_status(now_ms)
        log.info(
            "Uplink: %d report(s) for %d device(s), %d problem(s)",
            len(reports),
            len(per_device),
            len(errors),
        )

    async def _publish_device(
        self,
        device_id: str,
        items: list[tuple[bridge.ModuleMapping, dict, int]],
        now_ms: int,
    ) -> list[str]:
        """Write one device's io_state messages, merge its io_state aggregate and
        refresh its connection status. Returns any problems, never raises."""
        label = self._device_label(device_id)
        problems: list[str] = []
        agent = int(device_id)
        merged: dict[str, Any] = {}
        for mapping, report, _ in items:
            fields = bridge.build_io_state(mapping, report, now_ms)
            if not fields:
                continue
            merged.update(fields)
            try:
                await self.api.create_message(
                    self.state_channel, fields, agent_id=agent
                )
            except Exception as exc:  # noqa: BLE001 - reported on the page
                log.warning("io_state message to %s failed: %s", device_id, exc)
                problems.append(f"{label}: {_short(exc)}")
                return problems

        if merged:
            try:
                await self._merge_aggregate(agent, self.state_channel, merged)
            except Exception as exc:  # noqa: BLE001
                log.warning("io_state aggregate on %s failed: %s", device_id, exc)
                problems.append(f"{label}: state not saved ({_short(exc)})")

        if getattr(self.config.mark_online, "value", True) is not False:
            heard_ms = max(h for _, _, h in items)
            try:
                await self._mark_online(agent, heard_ms, now_ms)
            except Exception as exc:  # noqa: BLE001
                log.warning("Connection status on %s failed: %s", device_id, exc)
                problems.append(f"{label}: online status not set ({_short(exc)})")
        return problems

    async def _merge_aggregate(self, agent: int, channel: str, fields: dict):
        try:
            existing = await self.api.fetch_channel_aggregate(channel, agent_id=agent)
            data = getattr(existing, "data", None)
        except Exception:  # noqa: BLE001 - a missing channel or aggregate
            data = None
        if isinstance(data, dict) and data:
            await self.api.update_channel_aggregate(channel, fields, agent_id=agent)
        else:
            # A missing or null aggregate takes no PATCH, so seed it whole.
            await self.api.update_channel_aggregate(
                channel, fields, replace_data=True, agent_id=agent
            )

    async def _mark_online(self, agent: int, heard_ms: int, now_ms: int):
        expected_s = int(_num(self.config.expected_interval_min, 15.0) * 60)
        offline_s = int(_num(self.config.offline_after_min, 90.0) * 60)
        signature = f"{expected_s}/{offline_s}"
        cfg_key = f"c{agent}_conn"
        if self.get_tag(cfg_key) != signature:
            await self.api.update_connection_config(
                ConnectionConfig(
                    ConnectionType.periodic,
                    expected_interval=expected_s,
                    offline_after=offline_s,
                ),
                agent_id=agent,
            )
            await self.set_tag(cfg_key, signature)

        online = (now_ms - heard_ms) <= offline_s * 1000
        await self.api.ping_connection_at(
            online_at=datetime.fromtimestamp(heard_ms / 1000, tz=timezone.utc),
            connection_status=ConnectionStatus.periodic_unknown,
            determination=(
                ConnectionDetermination.online
                if online
                else ConnectionDetermination.offline
            ),
            user_agent=USER_AGENT,
            agent_id=agent,
        )

    # -- downlink -------------------------------------------------------------

    async def handle_command(self, device_id: str, data: Any, now_ms: int):
        if not bridge.is_command(data):
            return  # the edge's reply, or something else on the channel
        message, problem = bridge.command_downlink(
            self.mappings, device_id, data, now_ms
        )
        label = self._device_label(device_id)
        if message is None:
            await self._set("downlink_errors", f"{label}: {problem}")
            await self.refresh_errors()
            return
        await self._forward(
            message,
            f"{data.get('command')} {data.get('target')} → module "
            f"{message['module']} ch {message['channel']} ({label})",
            now_ms,
        )

    async def handle_settings(self, device_id: str, data: Any, now_ms: int):
        if not isinstance(data, dict):
            return
        fingerprint = bridge.settings_fingerprint(data)
        key = settings_fp_key(device_id)
        if self.get_tag(key) == fingerprint:
            return
        message = bridge.settings_downlink(self.mappings, device_id, data, now_ms)
        if await self._forward(
            message, f"settings for {self._device_label(device_id)}", now_ms
        ):
            await self.set_tag(key, fingerprint)

    async def reconcile_settings(self, now_ms: int):
        """Forward any device's settings that changed without an event reaching us."""

        async def fetch(device_id: str):
            try:
                agg = await self.api.fetch_channel_aggregate(
                    self.settings_channel, agent_id=int(device_id)
                )
                return device_id, getattr(agg, "data", None), None
            except Exception as exc:  # noqa: BLE001
                return device_id, None, exc

        results = await asyncio.gather(*(fetch(d) for d in self.devices))
        for device_id, data, exc in results:
            if exc is not None:
                text = _short(exc)
                if text == "permission denied":
                    await self._set(
                        "downlink_errors",
                        f"{self._device_label(device_id)}: {text} reading settings",
                    )
                continue
            if isinstance(data, dict) and data:
                await self.handle_settings(device_id, data, now_ms)

    async def _forward(self, message: dict, summary: str, now_ms: int) -> bool:
        try:
            await self.api.create_message(self.downlink_channel, message)
        except Exception as exc:  # noqa: BLE001
            log.warning("Downlink forward failed: %s", exc)
            await self._set("downlink_errors", f"Downlink not sent: {_short(exc)}")
            await self.refresh_errors()
            return False
        log.info("Forwarded downlink: %s", summary)
        await self._set("last_downlink", now_ms)
        await self._set("last_downlink_text", summary)
        await self._set(
            "downlinks_forwarded", int(self.get_tag("downlinks_forwarded") or 0) + 1
        )
        await self._set("downlink_errors", "")
        await self.refresh_errors()
        return True

    # -- status ---------------------------------------------------------------

    async def refresh_status(self, now_ms: int):
        heard = {
            str(m.module): self.get_tag(module_heard_key(m.module))
            for m in self.mappings
        }
        text, fresh, expected = bridge.modules_summary(
            self.mappings,
            heard,
            now_ms,
            _num(self.config.module_stale_min, 120.0),
        )
        await self._set("modules_text", text if expected else "No modules mapped")
        await self._set("modules_fresh", fresh)
        await self._set("modules_expected", expected)
        await self._set(
            "bridge_status",
            bridge.bridge_status(
                self.get_tag("last_uplink"),
                now_ms,
                _num(self.config.uplink_timeout_min, 30.0),
            ),
        )
        await self.refresh_errors()

    async def refresh_errors(self):
        parts = [
            self.get_tag(key) or ""
            for key in ("config_errors", "uplink_errors", "downlink_errors")
        ]
        text = "; ".join(p for p in parts if p)
        await self._set("errors_text", text)
        await self._set("errors_hidden", not text)

    # -- helpers --------------------------------------------------------------

    def _device_label(self, device_id: str) -> str:
        device_map = (getattr(self, "received_deployment_config", None) or {}).get(
            "DEVICE_MAP"
        ) or {}
        entry = device_map.get(str(device_id)) or {}
        return entry.get("display_name") or entry.get("name") or f"device {device_id}"

    async def _set(self, key: str, value):
        if self.get_tag(key) != value:
            await self.set_tag(key, value)
