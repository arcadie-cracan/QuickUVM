# hybrid_alert — a HYBRID (initiator + responder) agent

**Can one QuickUVM agent both ANSWER the DUT and INITIATE stimulus at once?** Yes — this is
the `proactive: true` feature. OpenTitan's alert-sender is the motivating case: it answers the
receiver's liveness **pings** (reactive) AND spontaneously **raises alerts** (proactive). Until
now QuickUVM's `mode` was initiator XOR responder — no single agent could do both.

```yaml
agents:
  - name: sndr
    mode: responder        # we answer the DUT's pings...
    request_valid: ping
    respond: on_request
    proactive: true         # ...AND we spontaneously raise alerts (the hybrid)
```

The agent stays a responder — the env still forks its responder sequence, which answers each
ping — but it **also** joins the stimulus agents, so the test starts a proactive sequence
(`alert_raise_seq`) on the **same** sequencer. UVM arbitrates the two: the responder sequence
blocks on the request FIFO; the proactive sequence drives when it has an alert. **620/620 on
Xcelium, 0 errors** (`make regress` 2/2).

## The subtlety this closes: DEAD_RESPONDER is maskable

A responder's liveness is the `DEAD_RESPONDER` check — "the driver drove at least one response"
(`m_responses != 0`), because a dead responder is otherwise unprovable per-transaction. But a
hybrid **also** drives proactive alerts, which inflate that same count: a stone-dead
ping-responder would still look alive because the alerts kept the driver busy.

So a proactive responder gets a different, **un-maskable** liveness — the **request-FIFO drain**
on its sequencer. Proactive stimulus never touches the request FIFO; only the responder sequence
drains it. So an unanswered ping always shows, no matter how many alerts flowed:

```systemverilog
function void check_phase(uvm_phase phase);   // generated on the sequencer
  if (request_fifo.used() != 0)
    `uvm_error("DEAD_RESPONDER", "... observed request(s) were never answered ...")
endfunction
```

[MUTATIONS.md](MUTATIONS.md) proves it: kill the responder while the alerts keep flowing, and
this drain check fails the test with 129 unanswered pings — while the comparator still reports
"TEST PASSED" and the driver's drive-count check stays green (masked). That green-while-dead is
exactly what the drain prevents.

## Run

```
cd sim
xrun -f xrun.f +UVM_TESTNAME=hybrid_test
# or the seed regression:
cd ../gen && make regress
```
