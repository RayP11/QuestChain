# Web search providers

QuestChain uses Tavily by default. Existing `/tavily` setup, saved keys, search
behavior, and page extraction remain unchanged unless you select another provider.
Search tool permissions still apply to each agent.

## Use your own SearXNG instance

Operate a trusted [SearXNG instance](https://docs.searxng.org/admin/installation.html)
and enable `json` alongside `html` in its `search.formats` settings. JSON disabled
commonly produces HTTP 403. QuestChain does not install a server or choose a public
instance for you. Bind a local server to loopback; do not expose an unauthenticated
search service to the Internet.

Add these settings to the workspace `.env` (or the data-directory `.env`, which
workspace settings override), then restart QuestChain:

```dotenv
WEB_SEARCH_PROVIDER=searxng
SEARXNG_SEARCH_URL=http://127.0.0.1:8080/search
```

The URL is the **complete search endpoint**, including any deployment prefix, e.g.
`https://search.example.com/searxng/search`. Plain HTTP is accepted only for a
numeric loopback address (`127.0.0.1` or `[::1]`); use HTTPS with a valid certificate
for remote instances. Credentials, query strings, and fragments are rejected.
Authentication headers and custom CA configuration are not supported by this first
integration. Configure a trusted network path; don't disable TLS verification.

The model supplies only a query. It cannot choose the instance, request headers,
result count, or request parameters. Settings display the active search provider;
agent tool diagnostics explain missing configuration. Invalid configuration disables
search instead of falling back. Configuration diagnostics indicate syntax/readiness,
not a successful health check.

**SearXNG mode disables `web_browse`**, including when a saved Tavily key exists.
It returns titles, URLs, and snippets only. There is no new page fetcher. `/tavily`
can still save a key but does not change the selected provider. Switch back with
`WEB_SEARCH_PROVIDER=tavily` (or remove it) and restart to restore Tavily search and
extraction. Unknown providers disable both tools. No data migration is needed.

## Privacy and security boundaries

Self-hosted is not offline. The query goes to your configured instance, which
contacts its configured upstream engines. The instance operator, upstream engines,
and infrastructure may observe it. SearXNG explains the distinction in its
[private-instance guide](https://docs.searxng.org/own-instance.html). Do not put
secrets in searches. SearXNG search syntax can select engines: configure/restrict
available engines on the server if upstream choice matters.

The client POSTs form data to keep queries out of request URLs. It adds no query or
exception-body logging. HTTP client logging may include the configured endpoint;
never put secrets in its path. QuestChain conversations, tool events/history,
optional tracing, and server/reverse-proxy logs may still contain queries/results.
This integration is not a promise of end-to-end log redaction or anonymity.

Requests have a 15-second total network deadline and 5-second connect timeout;
responses are streamed with a 1 MiB raw-byte ceiling. Compressed responses are
rejected, redirects are not followed, and there are no retries or public-service
fallbacks. Output is limited to five results with 300-character titles,
2,000-character snippets, and 2,048-character URLs. Per-call clients do not share
cookies or consult environment proxies or netrc credentials. Consequently, this
backend needs direct access to its configured service; proxy-only networks are not
supported. HTTPX was already a transitive dependency and is now declared directly.

Responses with reported upstream engine failures have `status: degraded` and a
fixed warning. Usable partial results are retained; if none remain, the tool also
returns an error rather than treating the response as evidence of no matches.
The response does not establish whether all engines failed. Engine names and
failure details are not exposed, and degradation never triggers retries or a
fallback provider. An empty result list without reported failures is still a
successful response (`status: ok`). Non-list upstream-status metadata fails with
a sanitized error; entries within a nonempty list are treated as opaque failures.

The endpoint is **trusted operator configuration**, not an arbitrary-URL tool.
HTTPS endpoints may intentionally reach private services; DNS is not pinned and
private HTTPS destinations are not blocked. Restrict configuration access and use
network egress policy if configuration or DNS is untrusted. Enabled shell/custom
Python tools can also modify configuration using the application's OS privileges;
this feature adds no OS sandbox.

Result URLs are never fetched. Unsafe schemes, credentials, control characters,
obvious local names, and non-public literal IPs are filtered, but this is not DNS
validation or a guarantee a link is safe to visit. Future URL consumers must apply
their own SSRF/redirect/DNS controls. Results are returned as structured, explicitly
untrusted data; the model is instructed not to follow embedded instructions. That
label reduces confusion but cannot eliminate prompt injection. Existing tool
allowlists and human judgment remain necessary for consequential actions.

## Why this backend?

| Option | Execution and privacy | Dependency/licensing considerations |
| --- | --- | --- |
| [SearXNG](https://github.com/searxng/searxng) | Operator-selected service; queries still reach upstream engines. A documented [POST/JSON API](https://docs.searxng.org/dev/search_api.html) fits the existing tool. | Separately operated AGPL-3.0 server; no server code bundled. Operators must review their server distribution/modification obligations. |
| [Brave Search API](https://brave.com/search/api/) | Hosted search with an API key; does not meet the self-hosted goal. | Commercial API terms and upstream service dependence remain. |
| [Open-WebSearch](https://github.com/Aas-ee/open-webSearch) | Local Node/MCP/daemon client performs remote multi-engine searches and content retrieval. Local execution does not remove network disclosure. | Apache-2.0; broader scraper/fetcher/runtime surface than this change needs. A [past SSRF advisory](https://github.com/Aas-ee/open-webSearch/security/advisories/GHSA-v228-72c7-fx8j) was patched in 2.1.7; that is not a claim current releases are vulnerable. |
| [DDGS](https://github.com/deedy5/ddgs) | Python metasearch client with backend selection; queries still go to external services. | MIT; additional backend-selection/privacy and scraping maintenance review required. |

The adapter is original QuestChain code under the repository's MIT license. No
SearXNG/Open-WebSearch/DDGS implementation is copied or bundled. Operating a separate
service does not waive that service's license or search engines' terms. The choice
here is a narrow integration, not a general legal assessment or upstream security audit.
