# Zomato MCP

Implementation for the official endpoint https://mcp-server.zomato.com/mcp.
Source: https://github.com/Zomato/mcp-server-manifest.

This connector is not verified connected. Client/callback approval and account
authorization remain deferred. Vellum registers only its own client and callback
(http://localhost:8000/api/plugins/zomato/oauth/callback); it does not reuse another
client identity, redirect, credential or grant. A successful token exchange and
authenticated catalog are required before readiness is reported.

Authorization uses the existing OS credential store and MCP OAuth owner. The
complete approved catalog is discovered on demand. Reads and reviewed operations
use the existing ToolRegistry, PluginMcpRuntime and App Action receipts.
