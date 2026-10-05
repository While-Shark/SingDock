# Upstream baseline

- Source: https://github.com/Alvin9999-newpac/Sing-Box-Plus
- Reference commit: 949bfcb8074a3f397220d5893869e63f3e51faa3
- File: sing-box-plus.sh (v4.8.0)
- Original blob: 4faca8043673ca73694a2128434878edbfa83938
- sing-box: v1.13.7, matching upstream's pinned default.

The upstream root currently contains a stable script and two test variants. SingDock vendors only the stable script, not redundant test variants.

The vendored file changes only:

1. Guard stty when stdin is not a terminal.
2. Guard the final menu call with SINGDOCK_SOURCE_ONLY so the container adapter can load its functions.

Container changes live in docker/: no systemd installation, firewall mutation, runtime package installation or BBR mutation. Supervisor controls processes; Tini handles PID 1 and signals. The adapter fixes duplicate port allocation caused by subshell array changes, validates configuration before replacing it, removes unused legacy block outbounds for sing-box 1.13 and removes WARP listeners when disabled. It explicitly sets route.default_domain_resolver in both WARP and direct modes to satisfy sing-box 1.13 DNS requirements.

Upstream attribution is retained in the vendored file. No LICENSE file was present in the inspected upstream root; SingDock does not assign a new license to upstream code. Confirm redistribution/licensing terms with the original author before broader distribution.

To follow upstream, compare this fixed baseline against the new stable script, keep the two source guards, then run the container smoke test and protocol-specific checks. Do not replace the adapter with host installation logic.
