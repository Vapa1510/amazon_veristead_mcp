# Veristead - Hackathon Friction Log

## Record: FastMCP PRM Resource Field Overlap (Issue #1348)
**Date Recorded:** September 13, 2026
**Component:** OAuth 2.1 layer (FastMCP `GitHubProvider`)
**Context:** Alexa+ / AWS Builder mini-challenge

### The Friction
During Phase 2 (integrating OAuth 2.1 via FastMCP’s native `GitHubProvider`), we encountered a subtle but critical failure point mapped to FastMCP's Protected Resource Metadata (PRM) endpoint structure.

By default, the `base_url` supplied to the provider is supposed to accurately reflect the metadata discovery endpoint (`.well-known/oauth-protected-resource`). However, due to a known bug in this iteration of FastMCP (tracked upstream in GitHub issue #1348), the internal router occasionally drops or incorrectly maps the resource URL returned in the WWW-Authenticate header and metadata document when running under specific path setups, leading to a 404 Not Found condition during client discovery.

### The Impact
If left to the default constructor:
```python
auth = GitHubProvider(
    client_id=client_id,
    client_secret=client_secret,
    base_url=base_url
)
```
A native MCP client receiving the initial 401 Unauthorized would follow the resource link to fetch authorization URLs, only to hit a dead end. This directly breaks the PKCE authentication handshake completely, blocking secure tool execution and rendering the server useless to authenticated surfaces.

### The Resolution
To overcome this friction transparently, we explicitly mapped all internal identifiers manually rather than trusting the fallback defaults. We hard-wired the configuration to coerce the `resource_base_url` and `issuer_url` explicitly into alignment with the `base_url`:

```python
auth = GitHubProvider(
    client_id=client_id,
    client_secret=client_secret,
    base_url=base_url,
    resource_base_url=base_url,  # Explicit PRM mapping fix
    issuer_url=base_url,         # Explicit Issuer mapping fix
)
```

Additionally, to ensure local, pre-deployment development is completely insulated from this OAuth layer volatility, we integrated a conditional fallback inside `_build_auth()`. If the OAuth environment variables are stripped out, the server gracefully boots in a local open mode, allowing purely logical development with the MCP Inspector without being blocked by network or OAuth friction.
