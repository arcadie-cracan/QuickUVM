# alert_array — mutation proofs

Baseline: **3× TEST PASSED — 499 Ran / 499 Passed each, 0 errors** (one hybrid alert-sender per
channel: each answers its ping and raises its alerts, each independently checked). Two mutations,
both showing per-replica independence — the whole point of composing `count` with the hybrid agent.

## M1 — the proactive path (per-channel scoreboard)

Mutation (`rtl/alert_array.sv`): channel 1 latches a corrupted payload —

    else if (alert[i]) last_adata[i*DW +: DW] <= (i==1) ? ~adata[i*DW +: DW] : adata[i*DW +: DW];

Result: **only `sndr_1`'s scoreboard fails** (≈992 errors, all from `alert_array_sndr_1_comparator`;
`sndr_0` and `sndr_2` stay 499/499). The N per-channel scoreboards are independent.

## M2 — the reactive liveness (per-replica drain) — the composition's point

Mutation: hang **only replica 1's** responder. The responder sequence is a shared class, so the
mutation keys off the sequencer path to kill exactly one replica:

    if (uvm_re_match("sndr_1_", p_sequencer.get_full_name()) == 0) wait(0);   // kill replica 1

Result: **only `sndr_1_agnt.sqr`'s DEAD_RESPONDER fires**:

```
UVM_ERROR sndr_sequencer.svh(42): uvm_test_top.e.sndr_1_agnt.sqr [DEAD_RESPONDER]
          123 observed request(s) were never answered ...
UVM_ERROR : 1
```

`sndr_0` and `sndr_2` drain their own ping FIFOs and pass. This is the load-bearing result: each of
the N hybrid replicas carries its **own** request-FIFO-drain liveness on its **own** sequencer, so a
dead responder in one alert channel is caught **independently** — it is neither masked by, nor masks,
the other N−1. That is exactly what an alert-sender array needs: N independent liveness checks, one
per channel, none of them fooled by the proactive alert traffic on any channel.
