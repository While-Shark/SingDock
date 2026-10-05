# Security review

This review covers the container adapter, vendored script execution paths, GUI authentication/routing/request handling, configuration persistence, and Compose privileges. It does not certify the project as vulnerability-free or replace an image/dependency CVE scan.

## Findings and fixes

| Finding | Exposure | Fix |
| --- | --- | --- |
| Persisted node settings executed with shell `source` | An attacker who could alter a bound data file could execute commands with the container's management privileges. No unauthenticated HTTP path to write these files was found. | Replace execution with a per-file key allowlist, literal values, duplicate-key rejection, bounded regular-file reads and `O_NOFOLLOW`. Disallow overriding the core executable. |
| Writable bootstrap directory prepended to PATH | A tampered executable in the data directory could be selected by privileged management commands. | Move bootstrap executables outside the data volume and reset the management PATH to trusted system directories. |
| Unbounded HTTP worker creation and unlimited failed logins | Repeated connections or password guesses could consume resources. | Bound HTTP workers to 16; limit failures to 10 per peer per 60 seconds and 100 globally per window; bound limiter memory and return 429 with Retry-After. |
| Ambiguous request lengths | Duplicate Content-Length or Transfer-Encoding could cause inconsistent parsing at a proxy boundary. | Reject both; enforce one bounded Content-Length and reject incomplete bodies before applying changes. |
| Excess container privileges and readable data directories | Unnecessary Linux capabilities increase the impact of a compromise; permissive data directories expose stored secrets. | Enable no-new-privileges; drop NET_RAW, MKNOD and SYS_CHROOT; restrict data/runtime/WARP directory permissions to 700. README requires .env mode 600 and private backup umask. |

Regression tests include literal command-substitution/backtick payloads, actual Bash adapter loading without marker execution, unknown/PATH/BASH_ENV keys, executable overrides, duplicate keys, symbolic links, oversized settings, login limit expiry, global failure budgets, worker saturation and conflicting HTTP lengths. Existing authentication, CSRF, path isolation, rollback and credential-omission tests remain enabled. Container smoke exercises the reduced capability flags on AMD64/ARM64 in bridge/host modes.

## Deployment boundaries

- Keep the GUI bound to loopback and access it through an SSH tunnel or an HTTPS reverse proxy. [Python's http.server documentation](https://docs.python.org/3.11/library/http.server.html) does not recommend direct production use; these bounds do not turn it into a hardened public ingress server.
- Basic authentication needs encrypted transport. The custom path is not a substitute for authentication. Do not share the browser credentials or node links.
- Failed-login limits use the TCP peer address, not untrusted X-Forwarded-For. A reverse proxy's clients share its bucket. Apply independent connection/body timeouts and rate limits at the proxy; a temporary lockout may affect legitimate users behind the same peer.
- Authentication throttling follows the principle in the [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html). Counters are in-memory and reset when the GUI restarts.
- The container still runs as root for the existing adapter/WARP lifecycle. It has no Docker socket, privileged flag or NET_ADMIN capability by default. Host administrators and users who can control Docker must be trusted.
- Trusted system executables and the immutable application files must not be mounted from untrusted writable directories. Node data files are now data, but anyone who can alter them may still disrupt service or change node credentials.
- Self-signed protocol links and client-specific certificate validation remain an upstream compatibility choice. Use certificate pinning/trust options supported by your client rather than treating disabled certificate verification as a production security guarantee.
- WARP runtime remains experimental. Build/binary checks do not prove registration, egress or kernel compatibility. Full image CVE analysis was not run in this local environment because Docker/scanner binaries are unavailable.
