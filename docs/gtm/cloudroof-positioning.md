# cloudroof positioning frame (Obviously Awesome)

**Plan:** `docs/plans/2026-06-25-001-feat-gtm-rent-a-human-executor-plan.md` (U8, R13)
**Date:** 2026-06-25 · **Status:** draft frame for validation; refine against real discovery

Positioning chooses the frame of reference that makes value obvious. cloudroof's
value is invisible until the alternatives — especially "do nothing / self-host" —
are named. Components in order:

## 1. Competitive alternatives (what they'd pick otherwise)

- **Self-host wgmesh (free AGPL)** — the status quo and **fiercest competitor**.
  Costs the user time: provisioning, upgrades, monitoring, key rotation, uptime.
- **Headscale** — self-hosted Tailscale control-plane; still self-operated.
- **Tailscale (hosted)** — managed, but proprietary and not wgmesh's mesh model.
- **Do nothing** — keep the current ad-hoc VPN / no mesh.

## 2. Unique attributes (true only relative to the above)

- Managed hosting of the **AGPL wgmesh** product — no proprietary lock-in; the
  software stays free and self-hostable (no component paywall per CONSTITUTION.md).
- Operator removes the self-host toil (upgrades, monitoring, uptime) without
  taking the capability hostage.

## 3. Value + proof (the "so what")

- **Value:** time-to-running-mesh and ongoing uptime without operating it yourself.
- **Proof (to gather):** time-to-first-mesh on cloudroof vs a self-host install;
  the hours/month a self-hoster spends on upgrades + monitoring.

## 4. Target segment (buys fast, refers)

- A technical team/operator who **wants the wgmesh mesh model** but does not want
  to run the control plane — already self-hosting *something* and feeling the toil.
  (Sharpen against real discovery; see the Mom-Test kit.)

## 5. Market category

- **Managed mesh-VPN hosting** for an open-source mesh — framed against self-hosting,
  not against proprietary VPNs.

## The decisive question (validate first)

Does self-host friction exceed the price? cloudroof only sells if the toil it removes
is worth more than the subscription. That is the WTP hypothesis the discovery talks
(Mom-Test kit) must test before the service buildout scales.
