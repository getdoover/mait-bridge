from pydoover.tags import Tag, Tags

# Per-module tags are keyed by module number and written straight through the
# tag manager, because the set of modules comes from config:
#   m<module>_heard   epoch ms the module was last heard (drives the page)
# Per-device settings fingerprints, so a settings change is forwarded once:
#   s<device id>_fp


def module_heard_key(module: int) -> str:
    return f"m{module}_heard"


def settings_fp_key(device_id: str) -> str:
    return f"s{device_id}_fp"


class MaitBridgeCloudTags(Tags):
    bridge_status = Tag("string", default="Waiting for the first uplink")
    last_uplink = Tag("number", default=None)
    modules_text = Tag("string", default="None heard yet")
    modules_fresh = Tag("number", default=None)
    modules_expected = Tag("number", default=None)
    devices_mapped = Tag("number", default=None)

    last_downlink = Tag("number", default=None)
    last_downlink_text = Tag("string", default="None forwarded yet")
    downlinks_forwarded = Tag("number", default=0)

    # Problems from the latest uplink and the latest downlink, shown together.
    uplink_errors = Tag("string", default="")
    downlink_errors = Tag("string", default="")
    config_errors = Tag("string", default="")
    errors_text = Tag("string", default="")
    errors_hidden = Tag("boolean", default=True)
