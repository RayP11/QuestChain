# Web search providers

Fresh installations with no configured provider or Tavily key use **experimental
DDGS / DuckDuckGo search** without an API key, account, or service setup. It is an
unofficial client for a remote search service, **not** a locally hosted index,
offline search, or an official DuckDuckGo API. Searches send query text and the
network's outbound IP to DuckDuckGo (and through any operator-configured proxy).

## Defaults, migration, and provider selection

| Configuration at startup | Provider |
| --- | --- |
| No `WEB_SEARCH_PROVIDER`, no Tavily key | DDGS / DuckDuckGo |
| No `WEB_SEARCH_PROVIDER`, existing `TAVILY_API_KEY` | Tavily, preserving legacy behavior and extraction |
| Explicit `WEB_SEARCH_PROVIDER=ddgs` | DDGS, even if a Tavily key is saved |
| Explicit `WEB_SEARCH_PROVIDER=searxng` | Configured SearXNG only |
| Explicit `WEB_SEARCH_PROVIDER=tavily` | Tavily only; key required |
| Explicit `WEB_SEARCH_PROVIDER=none` | Search and extraction disabled |
| Unknown or empty explicit value | Disabled with configuration diagnostic; no fallback |

Restart after changing `.env`. Workspace settings override data-directory settings.
`/tavily` saves a key; it does not override an explicit provider. Without an explicit
provider, adding a key selects Tavily on the next restart. Search permissions still
apply per agent. DDGS and SearXNG both disable `web_browse`, even with an old Tavily
key. Neither mode fetches pages from result links. CLI banners, web Settings, tool
descriptions, and DDGS result metadata disclose the provider.

## Experimental DDGS adapter

The dependency is pinned to **ddgs==9.16.1**; the lockfile records its wheel hashes
and transitive lxml/primp versions. This adapter deliberately uses only that
version's DuckDuckGo payload builder and result parser. It does **not** call
`DDGS().text()`, the automatic backend dispatcher, the primp client, the thread
pool, `extract()`, the CLI, MCP, or API server. The default dispatcher can fall back
to auto for an unknown backend, and its failure/empty distinction is insufficient
for this integration. An installed-version/backend guard fails closed on mismatch.
Updates require re-reviewing and retesting the pinned parser contract.

QuestChain sends one POST to `https://html.duckduckgo.com/html/`, requesting the
first page with the fixed `us-en` region. Only query text is model-controlled. It
does not rotate providers, impersonate random browsers, solve CAPTCHAs, retry,
follow redirects, or paginate. DuckDuckGo's results may themselves originate from
its upstream partners; DDGS's provider metadata calls this a Bing-backed engine.
The parser does not implement SafeSearch selection; do not rely on this adapter as
a content safety filter.

Two requests at most run concurrently **per QuestChain process**, across tool
instances/agents; excess calls return busy immediately without queuing. Native
async HTTP means timeout/cancellation closes the active stream and releases the
slot; there are no worker threads left searching. The total network deadline is
15 seconds (connect timeout 5 seconds). Responses are streamed up to 1 MiB, and
compressed bodies are rejected. Parsing is synchronous after this bounded read;
the network deadline is not a CPU sandbox. Only five safe-scheme URLs, bounded
titles and snippets are returned with an untrusted-data notice. Result URLs are
never fetched; the URL limitations described below also apply.

The HTTP transport respects operator proxy and CA environment settings with TLS
verification enabled. A configured proxy sees traffic according to that proxy's
policy. It does not use DDGS_PROXY, share cookies between calls, or send queries in
request URLs. Errors contain fixed messages without queries, response bodies, or
upstream exceptions. Existing app history/tracing and upstream/proxy logging can
still retain queries and results. No claims of anonymity or end-to-end log redaction
are made.

A 403/429, redirect, challenge, timeout, incompatible encoding, or transport failure
is **unavailable**, never a successful empty search. An empty HTTP 200, changed
markup, or no usable parsed results is **inconclusive**: it could mean no matches,
blocking, or parser drift. There is no claim that no matching pages exist. This
unofficial integration can stop working when DuckDuckGo changes its pages or access
policy. Configure SearXNG or Tavily explicitly if you need another provider; failures
never select one for you.

### License and upstream terms: unresolved production suitability

The installed DDGS wheel contains the [MIT license](https://github.com/deedy5/ddgs/blob/v9.16.1/LICENSE.md),
but its [README disclaimer](https://github.com/deedy5/ddgs/tree/v9.16.1#disclaimer)
states: **“This library is for educational purposes only.”** The MIT software license
does not grant rights to DuckDuckGo's service, content, or trademarks.

[DuckDuckGo's terms](https://duckduckgo.com/terms) require compliance with its
[acceptable-use policy](https://duckduckgo.com/acceptable-use). That policy restricts
redisplaying portions of its service inside another service, resale, unauthorized
access, and disruptive activity. Returning search snippets in an agent UI raises a
material question under those restrictions. **This draft does not establish that
such use is permitted. Production/default-release suitability remains unresolved;
maintainers should resolve applicable provider permissions/terms before shipping
this experimental default.** Do not interpret a successful request or a permissive
client license as blanket permission for production automation. No bypass of
blocks, rate limits, or CAPTCHA is implemented.

The [privacy policy](https://duckduckgo.com/privacy) describes the information its
servers receive and how it is handled. Its privacy promises do not make a network
query local. Review service policies for your intended use and jurisdiction.

Review of the installed 9.16.1 package found no DHT/peer discovery or peer-cache
network path used by this adapter, despite P2P/DHT topics on the upstream repository.
Importing the engine registers other engine classes but does not execute them.
Tests prohibit network activity during import/parser-only work. This is a review
of the pinned path, not a guarantee about future releases or every DDGS feature.

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
`WEB_SEARCH_PROVIDER=tavily` and a saved key, then restart to restore Tavily search
and extraction. Removing the provider selects Tavily only if a key exists. Unknown providers disable both tools. No data migration is needed.

## SearXNG privacy and shared result-security boundaries

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
| [DDGS](https://github.com/deedy5/ddgs) | Experimental default using only the pinned DuckDuckGo parser; one explicit external endpoint. | MIT plus educational-only disclaimer; upstream terms/production suitability unresolved, as detailed above. |

The adapter is original QuestChain code under the repository's MIT license. No
SearXNG/Open-WebSearch server implementation is copied or bundled. DDGS is an
installed dependency with its own MIT license, not vendored source. Operating a separate
service does not waive that service's license or search engines' terms. The choice
here is a narrow integration, not a general legal assessment or upstream security audit.
