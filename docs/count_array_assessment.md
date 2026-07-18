# `count` — N agents into one vectored DUT: closing alert_handler I-9 (and the block)

The [alert_handler probe](alert_handler_assessment.md) named three [I] gaps. This closes the
**last** one — I-9, one agent instantiated ~63× into one DUT — as a built, mutation-proved feature
(`examples/nchan`). With I-8 (the [windowed scoreboard](parity_roadmap.md)) and I-7 (the
[hybrid agent](hybrid_agent_assessment.md)) already done, **all three of alert_handler's
architectural gaps are now closed.**

## The gap

alert_handler's whole economy is **one** `alert_esc_agent` definition **reused ~63×**, one per alert
line, into **one** block. QuickUVM's C3 `instances` gave each instance its own interface *and DUT*
(an 8-bit and a 16-bit datapath as separate benches) — the wrong topology for N identical channels
on one DUT.

## The feature: `count: N`

Opt-in on an agent. `count: N` replicates it N times into **one** DUT whose ports are vectored
`[N-1:0]` (times each port's width), with replica *i* bound to bit *i*. It reuses the C3 machinery
almost entirely: the per-instance agents, config, scoreboards, and sequences are the C3
`instance_views` wiring. The one genuinely new piece is tb_top — instead of C3's *one DUT per
instance*, `count` binds all N interfaces to one DUT via a concatenation `{inst_{N-1}, .., inst_0}`,
so bit *i* of each vector port is replica *i*'s signal. Opt-in and byte-identical when `count: 1`.

## Proof

`examples/nchan` — 3 identical 1-bit latch channels into one DUT: 3 agents, 3 per-channel
scoreboards, one vectored DUT. 3×102/102 on Xcelium, `make regress` 2/2. Mutation-proved
(`MUTATIONS.md`): corrupt **only channel 1** and **only `ch_1`'s scoreboard fails** — which proves
both per-channel independence *and* the index mapping (channel 1 → `ch_1` → `dut.q[1]`; a reversed or
shuffled binding would fail the wrong scoreboard).

## Scope — fail-closed, not silent

This is the replication + vectored-wiring core. Because `count` reuses the C3 per-instance env path
(which was built for per-instance DUTs), several combinations would *silently* mis-generate — an
adversarial review found a second agent dropped, coverage dropped, `inouts` dropped, multi-clock
mis-wired, a customized scoreboard flattened, and (a real compile bug) the default
`external_reset: false` binding an undeclared reset. The fix is fail-closed: each of these is now
**rejected with a clear error** rather than mis-generated. So `count > 1` is validated to be a bench
that is:

- a **single, sole agent** (no second agent yet — alert_handler's N alerts + a `tl_agent` is the
  follow-up, and needs `count` + the hybrid agent composed);
- **initiator** (`count` + `mode: responder` rejected — the reactive per-replica wiring is not yet
  validated; the alert-senders are hybrids, so this is the same follow-up);
- **single-clock**, **`external_reset: true`**, **no `inouts`**, **no coverage**, and with **plain
  single-stream scoreboards** only (a windowed/two-stream/out-of-order one is rejected).

The DUT the user supplies must declare its ports **vectored** (`[N-1:0]` × width); the generated DUT
*stub* is a scalar placeholder (as for any example, the real RTL is user-provided — the demo's
filelist compiles `rtl/nchan.sv`, not the stub).

None of these restrictions change the load-bearing result: one agent definition now drives N channels
of one DUT, each independently checked, with the slices provably mapped 1:1. They bound it to what is
*verified*, and turn every out-of-scope combination from a silent green into a loud error.

## alert_handler — closed

- **I-7** hybrid initiator+responder → `proactive: true`.
- **I-8** cycle-accurate reference model → the windowed scoreboard.
- **I-9** one agent × N into one DUT → `count` (this).

The probe's "hard break at the mapping stage" is now three shipped features. What remains for a
*complete* alert_handler bench is composition (hybrid + count together, the differential/ping
protocol in seams, the escalation timers as windowed checks) — integration, not missing primitives.
