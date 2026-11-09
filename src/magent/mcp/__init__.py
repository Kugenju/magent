"""Public surface of the MCP extension (phase 10, offline-safe by default).

Importing ``magent.mcp`` never imports the MCP SDK or any network library:
everything below works against the in-memory fake transport. Real transports
(stdio / streamable HTTP) live in ``magent.mcp.transports`` and lazily import
the SDK only when constructed — they are the module's only L2 network surface.

Typical offline usage::

    from magent.mcp import fake as mcp_fake
    from magent.mcp import McpServerConfig, McpToolLoader
    from magent.tools import ToolRegistry

    server = mcp_fake.FakeMcpServer("srv", [...])
    factory = mcp_fake.FakeTransportFactory(server)
    registry = ToolRegistry()
    loader = McpToolLoader(registry, [McpServerConfig("srv", factory, allow_tools=("echo",))])
    snapshot = await loader.load()
"""

from magent.mcp.errors import (
    KIND_ELICITATION_DENIED,
    KIND_TRANSIENT,
    McpInvalidConfigError,
    McpToolError,
)
from magent.mcp.loader import McpToolLoader
from magent.mcp.proxy import McpToolProxy
from magent.mcp.spec import (
    McpServerConfig,
    McpToolDescriptor,
    McpToolEntry,
    McpToolsetSnapshot,
    qualify_tool_name,
    snapshots_consistent,
)
from magent.mcp.schema import (
    SCHEMA_MODE_ABSENT,
    SCHEMA_MODE_TYPED,
    SCHEMA_MODE_UNTYPED,
    build_input_model,
)
from magent.mcp.transport import McpCallOutcome, McpTransport
from magent.mcp.fake import (
    FakeMcpServer,
    FakeToolDefinition,
    FakeTransportFactory,
    InMemoryMcpTransport,
    fake_outcome,
)

__all__ = [
    # naming/spec
    "McpServerConfig",
    "McpToolDescriptor",
    "McpToolEntry",
    "McpToolsetSnapshot",
    "qualify_tool_name",
    "snapshots_consistent",
    # transport seam
    "McpTransport",
    "McpCallOutcome",
    # adapter + loader
    "McpToolProxy",
    "McpToolLoader",
    # schema conversion
    "build_input_model",
    "SCHEMA_MODE_ABSENT",
    "SCHEMA_MODE_TYPED",
    "SCHEMA_MODE_UNTYPED",
    # errors
    "McpToolError",
    "McpInvalidConfigError",
    "KIND_ELICITATION_DENIED",
    "KIND_TRANSIENT",
    # offline doubles (testing)
    "FakeMcpServer",
    "FakeToolDefinition",
    "FakeTransportFactory",
    "InMemoryMcpTransport",
    "fake_outcome",
]
