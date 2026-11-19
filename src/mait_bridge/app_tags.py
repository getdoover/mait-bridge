from pydoover.tags import Tag, Tags


class MaitBridgeTags(Tags):
    status = Tag("string", default="Not yet connected (stub)")
    port = Tag("string", default=None)
    modules_heard = Tag("number", default=0)
    last_uplink = Tag("number", default=None)
    downlinks_received = Tag("number", default=0)
    last_downlink = Tag("number", default=None)
    last_downlink_text = Tag("string", default="None received")
