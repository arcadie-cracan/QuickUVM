# chip — H2 boundary agents: a subsystem with its own top-level agent

The chip-level UVM shape: **block envs inside, chip-boundary agents outside**
(OpenTitan's `chip_env` topology). Before H2, a subsystem bench could only compose
`subenvs:` — stimulus had to live in a leaf block. Now the top may declare `agents:`
alongside `subenvs:`, and the agent is a first-class endpoint:

```yaml
agents:                       # the chip-boundary agent
  - name: host
    ports:
      inputs:  [{name: hin,  width: 8}]   # driven: the subsystem's external input
      outputs: [{name: resp, width: 8}]   # sampled: the subsystem's response

subenvs:                      # the composed block envs (the pipe pipeline)
  - {name: add, config: add/add.yaml}
  - {name: inv, config: inv/inv.yaml}

connections:
  - {from: host.hin,  to: add.din}    # agent DRIVES a block input
  - {from: add.dout,  to: inv.din}    # block -> block (H1, unchanged)
  - {from: inv.dout,  to: host.resp}  # agent SAMPLES a block output

analysis:
  scoreboards:
    - {name: e2e, source: host, monitor: inv.b}   # BARE agent name as endpoint
```

## What the generator wires (all of it, no glue)

- `tb_top`: the boundary interface flat-style (`host_if host_if_inst (clk)`), the
  connection assigns in both directions, the vif into the config DB.
- The top env: builds `host_agnt`, hands it its cfg, collects `host_sqr` into the
  vsqr, connects `host_agnt.ap` straight to the `e2e` scoreboard (empty handle
  chain — the agent lives on this env).
- The top vseq: drives `host`'s default sequence concurrently with the blocks'.
- The top test pkg / filelists: `import host_pkg::*`, `-f host_pkg.f` — the
  boundary agent's package is generated exactly like a flat packaged bench's, so
  its files are byte-identical however it is hosted.

## Direction convention at the boundary

A **block** endpoint drives from its DUT's *outputs* (the leaf agent's sampled
ports). A **boundary agent** endpoint drives from the ports the agent *drives* —
its `inputs`, the house convention. `from: host.resp` (a sampled port) is rejected
fail-closed, as is `to: host.hin` (a driven port).

## Checking scales with stimulus

Drop the `e2e` scoreboard and the generated env raises, live in every sim log:

```
UVM_WARNING [UNCHECKED_AGENT] boundary agent 'host' is driven by the top vseq
            but no cross-block scoreboard checks its stream
```

## What runs, and the proof it can fail

Three scoreboards, all green on Xcelium (`101 Ran / 101 Passed` each, 0 errors):
`add`'s own (`dout == din+1`), `inv`'s own (`dout == ~din`), and the end-to-end
`e2e` (`inv.dout == ~(host.hin + 1)` — predicted from the *boundary agent's* stream).

| Mutation | Effect |
|---|---|
| wrong `e2e` model (`+2`) | **only** `e2e` fails (101/101 failed); both block scoreboards stay green |
| corrupt the subsystem (`add` → `din+2`) | `add`'s scoreboard **and** `e2e` fail; `inv`'s stays green (its local `~din` still holds) |
| drop the `e2e` scoreboard | `UNCHECKED_AGENT` fires at elaboration |

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=chip_test
```
