# Quiet Chaos

Quiet Chaos is a bounded, observable traffic noise generator for personal privacy experiments. It is a modern successor to older `noisy`-style crawlers, with explicit rate limits, safe HTTP methods, structured logs, Docker-first operation, a health endpoint, and optional OpenTelemetry.

The default configuration keeps traffic deliberately modest: bounded pacing between actions, GET/HEAD only, no form submission, no login automation, no captcha bypassing, and deny rules for local/private networks.

## Features

- Python 3.12+ async runtime using `httpx`.
- Traffic modes for HTTP browsing, DNS lookups, RSS polling, search-like Wikipedia API queries, and static asset HEAD requests.
- Automatic public seed-list refresh from Tranco with a local cache and built-in fallback seeds.
- Trend discovery enabled by default, with reviewable, reproducible daily pools and persistent budgets.
- Optional cached refresh of real browser user-agent strings.
- Browser-family request headers and bounded visited/failure caches to reduce repetitive traffic.
- Structured JSON logs for easy ingestion into Elastic, Loki, or other log tools.
- Built-in `/` health endpoint with runtime counters.
- Optional OpenTelemetry traces via the `otel` extra.
- Non-root Docker image, Compose example, GitHub Actions, Dependabot, Ruff, and pytest.

## Quick Start

Run on the Docker host with Compose:

```bash
docker compose up --build
```

Trend discovery is enabled by default, even when `[trend_sources]` is omitted.
The bundled local config uses token-free Tranco and Cisco Umbrella sources. The
first refresh requires outbound HTTPS access. Set
`[trend_sources].enabled = false` to opt out; an explicit `true` is also shown in
both example configs.

Check health:

```bash
curl http://localhost:8080
```

Compose binds the health endpoint to localhost by default. Put it behind an authenticated reverse proxy or explicitly change the port binding if remote access is required.

The container runs as `nonroot`, reads `/app/config.toml`, and stores refreshed seed and user-agent caches in the `quiet-chaos-cache` volume mounted at `/home/nonroot/.cache/quiet-chaos`.

For a dedicated Docker host, keep the host config at `/opt/quiet-chaos/config.toml` — [examples/config.srv.toml](examples/config.srv.toml) is an always-on host profile (no `run_for_seconds` cap, diurnal pacing) with trend discovery enabled. The Compose file bind-mounts this host file; rebuilding the image does not update it. Copy the template before first deploy, and copy it again when updating its settings:

```bash
cp examples/config.srv.toml /opt/quiet-chaos/config.toml
docker compose -f docker-compose.host.yml up -d
```

After changing the mounted config on an existing host, recreate the service so
the process loads it:

```bash
docker compose -f docker-compose.host.yml up -d --force-recreate
```

Useful host checks:

```bash
docker compose ps
docker compose logs -f quiet-chaos
docker inspect --format '{{json .State.Health}}' quiet-chaos-quiet-chaos-1
```

Refresh caches on the Docker host:

```bash
docker compose run --rm quiet-chaos run --config /app/config.toml --cache-dir /home/nonroot/.cache/quiet-chaos --refresh-seeds --once
```

Run locally:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
quiet-chaos run --config examples/config.toml --once
```

Refresh the Tranco seed cache:

```bash
quiet-chaos run --config examples/config.toml --refresh-seeds --once
```

## Configuration

Quiet Chaos uses TOML. Start with [examples/config.toml](examples/config.toml).

Important defaults:

- `request_timeout_seconds = 8.0`
- `max_response_bytes = 1000000` bounds both wire and decoded HTTP response bodies; oversized bodies fail without retries
- `modes = ["http", "dns", "rss", "search", "assets"]`
- `seed_sources` defaults to `https://tranco-list.eu/top-1m.csv.zip`
- `trend_sources.enabled = true` refreshes Tranco and Cisco Umbrella and adds their daily pool to seed selection; set it to `false` to disable provider refreshes and trend budgets
- `user_agent_source.enabled = false` by default; set it to `true` to cache fresh user agents from `useragents.me`
- `pacing.enabled = true` adds small bounded pauses between actions; see `[pacing]` in [examples/config.toml](examples/config.toml) for the tunable parameters
- `pacing.timezone` optionally selects an IANA zone such as `Europe/Amsterdam`; omitting it preserves runtime-local time, including in containers
- `stats_log.interval_seconds = 300` emits periodic structured counters for Docker log collection
- `max_request_retries = 1` retries transient network failures once with jittered backoff
- `seed_reinjection_probability = 0.1` occasionally returns to root seeds instead of only following discovered links
- `seed_sources` also supports `kind = "crux_gzip_csv"` for CrUX top-list CSV gzip files

### Trend Discovery

Trend discovery is enabled by default, adding a daily pool to the existing seed
selection. Discovery is separate from the seed sources. Set `enabled = false`
to turn it off. Provider refreshes require outbound HTTPS on startup. Inspect
without generating traffic, or replay a saved snapshot without provider
requests:

```bash
quiet-chaos trends --config examples/config.toml
quiet-chaos trends --config examples/config.toml --snapshot .cache/quiet-chaos/trends/snapshot-EXAMPLE.json --date 2026-11-06
```

The token-free baseline uses [Tranco](https://tranco-list.eu/) and the
[Cisco Umbrella popularity list](https://umbrella-static.s3-us-west-1.amazonaws.com/index.html).
Cisco publishes DNS-based daily rankings and dated historical lists; check
Cisco's current terms before relying on or redistributing its data. Snapshots
accumulate locally rather than downloading historical lists on startup. The
default profiles omit the full CrUX global CSV as a seed source because its
decompressed size currently exceeds the application's 32 MiB source limit;
CrUX remains an optional trend provider. Optional
[Majestic Million](https://majestic.com/reports/majestic-million) measures
referring subnets, not current visitors; its list is licensed CC BY 3.0 and
the full CSV is approximately 80 MB. Optional
[CrUX Top Million](https://github.com/zakird/crux-top-lists) is monthly and
its ranks are broad buckets, not exact positions.

For Cloudflare Radar, set `QUIET_CHAOS_RADAR_TOKEN` in the process environment
to a token with Account > Radar > Read permission. See
[Cloudflare's setup](https://developers.cloudflare.com/radar/get-started/first-request/)
and [ranking documentation](https://developers.cloudflare.com/radar/investigate/domain-ranking-datasets/).
Review provider terms before use. Radar's top 100 is individually ranked;
its larger weekly buckets are unordered. Radar is used when a token is present;
without one, discovery works with Tranco and Cisco. Tranco incorporates other
lists, including Radar, so source agreement is not statistical independence.

Each provider is attempted at most once per configured interval, including
failed attempts. Dated snapshots contain ranks, timestamps, HTTP validators,
source hashes, categories, decisions, and the final scores. A failed refresh
or ranking retains the last valid snapshot. When a static Tranco or CrUX source
matches an enabled trend provider, it reuses
that provider's observation, and `--refresh-seeds` does not bypass the trend
refresh interval. Registrable domains use the public suffix list bundled with
`tldextract`; updating the package updates that list without background downloads.
A new installation has no history: momentum is unknown until observations at
least seven days apart exist.
Momentum averages observed nonnegative relative rank improvement over the
seven- and 28-day lookbacks, with Radar observations weighted twice. The score
is 60% momentum, 30% normalized Tranco rank, and 10% source agreement;
unavailable components are omitted and weights renormalized. CrUX and Majestic
contribute only to agreement. Sampling without replacement uses the snapshot
hash and UTC date. Filters can leave fewer than the configured pool size.
Categories are operator-supplied; an allow-category filter excludes unknowns.
Popularity lists include infrastructure and are not guarantees of public
websites or content suitability; review the pool and configure deny rules.

Persistent UTC-day budgets default to 10 requests per registrable domain, 500
requests total, and 100 MiB of response wire-body bytes.
They cover all generated HTTP attempts, redirects, retries, and DNS actions,
not just trend origins. HTTPS is required in this mode. HTTP 429/503 causes a
per-domain cooldown honoring `Retry-After`, or one hour when absent or invalid.
The byte counter covers body bytes observed by the application, not HTTP/TLS
headers, DNS, discovery downloads, health, telemetry, or outbound traffic;
transport buffering may read ahead. Persistent reservations fail closed after
an interrupted request. Global exhaustion stops a continuous run. These are
not network-interface bandwidth limits.

## Safety Model

Quiet Chaos is designed for low-volume, benign background traffic. It does not try to bypass access controls, automate accounts, submit forms, exploit endpoints, or overwhelm services. Keep request rates conservative and follow the acceptable-use rules for the networks and services you run it against.

HTTP traffic, seed downloads, and user-agent downloads reject non-public IPv4
and IPv6 destinations, including redirects. Hostnames must resolve entirely to
public addresses; connections use a checked IP while preserving the original
Host header and TLS hostname to prevent DNS rebinding. Environment HTTP proxies
are not used, since they would bypass these destination checks. Telemetry export
is separately configured and is not subject to this HTTP traffic policy.

DNS mode intentionally queries the system-configured resolver, which may be on
a private network; it does not connect to returned addresses. Denied URLs are
not queried, lookup lifetime is bounded, and only entirely public A answers
are counted as successful lookups. HTTP DNS resolution separately validates
and pins connection addresses. This does not bypass local DNS configuration.

HTTP bodies are streamed and bounded before parsing, including gzip/deflate
decompression. Redirect bodies are closed without downloading them; every next
destination still passes the safety transport. Unsupported content encodings
are rejected. `response_body_bytes_received` counts observed HTTP body bytes
before decompression, including partial failed reads; it is not total network
traffic or outbound egress and excludes headers, DNS and TLS overhead.

### Health Access

Without an explicit configuration, the listener defaults to `127.0.0.1`.
Both container templates deliberately use `0.0.0.0` inside Docker and publish
only on host loopback. For direct local execution using either template,
change `health.host` to `127.0.0.1`. Host-loopback publishing does not isolate
the endpoint from other containers on the same Docker network.

Set `QUIET_CHAOS_HEALTH_TOKEN` in the process environment to require an
`Authorization: Bearer <token>` header. An unset variable leaves authentication
disabled; an empty or invalid token fails startup. Use a printable ASCII token
without spaces, keep it out of TOML/source control, and provision it through
your deployment's environment secret mechanism. Both Compose profiles pass
the variable through, and all container health probes use the same token.
Recreate containers after changing their environment. The endpoint uses plain
HTTP: keep it on a trusted interface or place it behind a TLS reverse proxy.

Only GET and HEAD on `/` are supported. Host names default to localhost,
loopback addresses and the concrete bind host. Add an intentional proxy's
Host name through `health.allowed_hosts = ["monitor.example"]`; wildcard binds
do not accept arbitrary Host names. Host validation is not authentication.
Health statistics expose exception class names, not error messages or requested
URLs. Detailed error logs can still contain URLs and should be access-controlled.

Dockerfile and Compose healthchecks intentionally use the same probe function:
Compose overrides the image check, while the image check covers `docker run`.
The host profile mounts
`/opt/quiet-chaos/config.toml` read-only; ensure the file is readable and its
parent directories are traversable by the container's `nonroot` user.

The Dockerfile pins Chainguard base images by manifest digest for reproducible
builds. To update them, inspect the desired Chainguard image manifests, update
both digest references, and rebuild the image.

### Telemetry

Install `quiet-chaos[otel]` (or `python -m pip install -e '.[otel]'` in a checkout)
and enable `[telemetry]` in TOML. The default container build installs only core
dependencies; a telemetry-enabled image must also install the `otel` extra.
The HTTP exporter honors standard OpenTelemetry environment variables:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` sets a base URL; the exporter appends `/v1/traces`.
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector:4318/v1/traces` sets the complete trace URL and takes precedence.
- `OTEL_EXPORTER_OTLP_HEADERS` or `OTEL_EXPORTER_OTLP_TRACES_HEADERS` configures collector credentials through the environment.

Without overrides, the HTTP exporter targets `http://localhost:4318/v1/traces`.
Inside Docker, use the collector service name for a separate container rather
than `localhost`. No additional TOML endpoint setting is required.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
semgrep scan --config p/python --config p/security-audit --error --strict --metrics off .
pytest
```

CI gates pull requests and releases with Semgrep as well as lint, formatting,
tests and a Docker build. Registry rules can evolve independently of the pinned
Semgrep version; findings and scan errors fail the check. Repository branch
protection must require the `security` check to enforce it before merging.

[Dependency Audit](.github/workflows/security.yml) runs weekly and on manual
dispatch for Python 3.12-3.14. It resolves runtime and optional telemetry
dependencies in a clean environment, audits their exact versions from separate
tooling, and retains JSON reports for 30 days even when advisories fail the job.
It excludes only the unpublished local project, not its dependencies. Audit
failures require investigation; no vulnerability IDs are automatically ignored.
Dependabot continues checking Python dependencies, Actions and Docker images.

## Releases

GitHub Releases mark checked source versions; they do not change deployment. Keep
Dockhand configured to track `main` and build locally using
[docker-compose.host.yml](docker-compose.host.yml). No packages or images are
published to PyPI or GHCR.

The host profile leaves `seed_urls` and `search_queries` unset so it inherits
the built-in topics, including the science and AI topics in the general example.
Rebuild and redeploy in Dockhand to pick up updated defaults. Explicit lists in
`/opt/quiet-chaos/config.toml` override those defaults and must be updated separately.

To release a version:

1. Update `[project].version` in [pyproject.toml](pyproject.toml) and merge the
	change into `main` through the usual review and CI checks.
2. Update your local `main` and run the checks:

	```bash
	git switch main
	git pull --ff-only origin main
	ruff check .
	ruff format --check .
	pytest
	```

3. Create and push an annotated tag matching the version exactly, prefixed with
	`v`. For version `0.2.0`:

	```bash
	git tag -a v0.2.0 -m "Release v0.2.0"
	git push origin v0.2.0
	```

Pushing a `v*` tag runs version validation, Ruff lint and format checks, pytest on
Python 3.12-3.14, and a Docker build without publishing the image. The tag must
equal `v` plus the version in the tagged commit's [pyproject.toml](pyproject.toml).
Only after all checks succeed does CI create a GitHub Release with notes from the
matching dated `CHANGELOG.md` section and GitHub's source archives; no wheel,
sdist, or container image is uploaded. Review the notes on GitHub after creation.

If checks fail, no release is created. Fix code failures on `main` and use a new
version and tag; do not move an existing release tag. For a transient CI failure,
rerun the failed jobs on the existing tag. If the release already exists, do not
rerun its creation job; edit its notes on GitHub instead.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
