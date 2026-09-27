# Veristead — Hackathon Friction Log

> AWS Builder mini-challenge format: task attempted → steps → expected vs. actual → severity → workaround → suggestion.

---

## 1. FastMCP Protected Resource Metadata Field Overlap

**Date:** September 13, 2026
**Component:** OAuth 2.1 layer (FastMCP `GitHubProvider`)

### Task Attempted
Integrate OAuth 2.1 + PKCE authentication via FastMCP's built-in `GitHubProvider`, so the MCP server can issue Bearer tokens to Alexa+ or any MCP client.

### Steps
1. Installed `fastmcp>=2.0` and imported `GitHubProvider`.
2. Configured the provider with `client_id`, `client_secret`, and `base_url`.
3. Started the server, attempted the OAuth PKCE flow from `test_client.py`.
4. Client received 401 → followed the `resource` link to discover authorization endpoints → hit a **404 Not Found** on the `.well-known/oauth-protected-resource` metadata endpoint.

### Expected vs. Actual
- **Expected:** The `base_url` parameter should be sufficient — the provider should derive the PRM (`/.well-known/oauth-protected-resource`) and issuer URLs automatically from it.
- **Actual:** Due to a known bug (upstream FastMCP GitHub issue #1348), the internal router occasionally drops or incorrectly maps the resource URL returned in the WWW-Authenticate header and metadata document under specific path setups, causing a 404 dead-end during client discovery.

### Severity
**Blocker.** The entire OAuth 2.1 handshake breaks at step 1 (client discovery). Without the fix, no authenticated tool execution is possible, and the server is useless to any authenticated surface including Alexa+.

### Workaround
Explicitly map all three URL fields instead of relying on the fallback defaults:

```python
auth = GitHubProvider(
    client_id=client_id,
    client_secret=client_secret,
    base_url=base_url,
    resource_base_url=base_url,  # Explicit PRM mapping fix
    issuer_url=base_url,         # Explicit Issuer mapping fix
)
```

Additionally, `_build_auth()` was designed with a conditional fallback: if OAuth env vars are absent, the server boots in open (unauthenticated) mode, insulating local development from OAuth-layer volatility.

### Suggestion
FastMCP should either (a) fix the URL derivation bug in `GitHubProvider` so `base_url` alone is sufficient, or (b) document that `resource_base_url` and `issuer_url` are required parameters, not optional ones. The current state is a silent failure that produces no error message — the server starts fine, but clients hit a dead end at runtime.

---

## 2. Alexa+ WWW-Authenticate Header Conflict

**Date:** September 14, 2026
**Component:** OAuth 2.1 middleware layer

### Task Attempted
Satisfy the Alexa+ MCP integration requirement: unauthenticated requests must receive `401` **without** a `WWW-Authenticate` header.

### Steps
1. Reviewed the Alexa+ Streamable HTTP spec requirements.
2. Observed that FastMCP's OAuth middleware automatically adds `WWW-Authenticate: Bearer` to every 401 response (standard RFC 6750 behavior).
3. Searched FastMCP's configuration API for a flag to disable this header — none exists.

### Expected vs. Actual
- **Expected:** A configuration option like `include_www_authenticate=False` on the auth provider, or a documented ASGI hook point.
- **Actual:** No configurability. The header is always emitted by the internal OAuth middleware.

### Severity
**Medium.** The header technically violates the Alexa+ spec, but the workaround is straightforward.

### Workaround
Built a custom ASGI middleware (`StripWWWAuthenticateMiddleware`) that intercepts 401 responses at the transport layer and strips the header before it reaches the client:

```python
class StripWWWAuthenticateMiddleware:
    async def __call__(self, scope, receive, send):
        async def wrapped_send(message):
            if message["type"] == "http.response.start" and message["status"] == 401:
                message["headers"] = [
                    (k, v) for k, v in message["headers"]
                    if k.lower() != b"www-authenticate"
                ]
            await send(message)
        await self.app(scope, receive, wrapped_send)
```

### Suggestion
FastMCP should expose a flag on the auth provider to control whether `WWW-Authenticate` is included in 401 responses. Different MCP surfaces have different requirements here — Alexa+ forbids it, but standard OAuth clients expect it.

---

## 3. Let's Encrypt Policy Block on AWS EC2 DNS

**Date:** September 25, 2026
**Component:** TLS / HTTPS deployment

### Task Attempted
Obtain a free TLS certificate via Let's Encrypt / Certbot for the EC2 instance's default public DNS (`ec2-X-X-X-X.compute-1.amazonaws.com`) to enable HTTPS without purchasing a custom domain.

### Steps
1. Installed Certbot via Snap on Ubuntu 24.04.
2. Ran `sudo certbot --nginx -d ec2-18-214-98-103.compute-1.amazonaws.com`.
3. Certbot returned: `Error creating new order :: Cannot issue for "ec2-...amazonaws.com": The ACME server refuses to issue a certificate for this domain name, because it is forbidden by policy`.

### Expected vs. Actual
- **Expected:** Let's Encrypt would issue a DV certificate for any publicly-resolvable domain.
- **Actual:** Let's Encrypt has a policy blacklist for `*.amazonaws.com` domains because they are transient and AWS-owned.

### Severity
**Medium.** Blocks HTTPS deployment on the free EC2 DNS, but there are free workarounds.

### Workaround
Used `nip.io` (a free magic DNS service) to create a stable domain that maps to the same IP: `18.214.98.103.nip.io`. Certbot successfully issues certificates for `nip.io` subdomains. Updated Nginx `server_name`, Certbot `-d` flag, and `OAUTH_BASE_URL` to use this domain.

### Suggestion
The hackathon resources page could mention this known limitation upfront and suggest `nip.io` or `sslip.io` as workarounds, since many participants will be deploying to EC2 without a custom domain.

---

## 4. Bedrock Model Access — Retired Manual Approval Page

**Date:** September 25, 2026
**Component:** AWS Bedrock onboarding

### Task Attempted
Enable access to Anthropic Claude models in the Bedrock console before making API calls.

### Steps
1. Navigated to the Bedrock console → Model Access page.
2. Discovered the manual "Request access" approval flow has been retired.

### Expected vs. Actual
- **Expected:** A gated approval page where you check a box and wait for access.
- **Actual:** AWS now auto-enables models on first invocation. First-time Anthropic model use prompts for a short use-case description, but there's no longer a waiting period.

### Severity
**Low (positive friction).** This is actually an improvement — it removed a multi-hour blocking wait from the onboarding flow. But the hackathon's Phase 0 checklist still references the old flow, which caused initial confusion.

### Workaround
None needed — just invoke the model directly. The first call triggers a brief use-case prompt, then access is granted immediately.

### Suggestion
Update the hackathon onboarding documentation to reflect the new auto-enable flow and remove references to the retired manual approval page.
