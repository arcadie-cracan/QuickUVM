# mclk — multi-clock / multi-reset (M1)

A two-clock-domain bench: the DUT has two independent registered lanes, each in
its own clock **and** reset domain, driven and checked by its own agent.

```
mclk.yaml
  clock:                         # the `clock:` key accepts a LIST of domains
    - {name: clk_sys, period: 10}
    - {name: clk_io,  period: 6}
  resets:                        # one external reset per domain, synced to its clock
    - {name: rst_sys_n, clock: clk_sys}
    - {name: rst_io_n,  clock: clk_io}
  agents:
    - {name: sys, clock: clk_sys, reset: rst_sys_n, ...}   # sys lane
    - {name: io,  clock: clk_io,  reset: rst_io_n,  ...}   # io  lane
```

- **`clock:` is a union** — a single mapping (every other example) stays
  byte-identical; a **list** declares a domain each. Internally it splits into a
  primary `clock` (the `-timescale` / scoreboard unit) + the full `clocks` list.
- **Each agent names its domain** with `clock:`/`reset:` (omit ⇒ the sole/first).
  QuickUVM resolves a per-agent view and:
  - emits one **parameterized `clkgen #(PERIOD)`** per clock
    (`clkgen #(10) ck_clk_sys`, `clkgen #(6) ck_clk_io`);
  - emits one **reset generator per reset**, each deasserting on its own clock's
    posedge, each in its own `reset_generator_<name>` pragma region;
  - binds each interface to its domain (`sys_if (.clk(clk_sys), .rst_sys_n(...))`)
    and derives the clocking-block drive skew from *that* domain's period (the io
    interface's skew is `#1.2` = 20 % of 6 ns, the sys interface's is `#2`);
  - reset-gates each driver/monitor on its own reset (`wait (vif.rst_io_n ...)`).

Both lanes are one register deep, so QuickUVM's input-@-posedge /
output-@-next-posedge monitor sampling checks each against the pure combinational
function of the sampled input (`sys_dout = sys_din + 1`, `io_dout = io_din ^ A5`).

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=mclk_test
```
Both scoreboards (`sys_sb` @ clk_sys, `io_sb` @ clk_io) pass **on Xcelium**
(0 errors) — two independently-clocked, independently-reset lanes.

## Scope / notes
- Fail-closed: an agent/reset naming an undeclared clock or reset; a reset name
  colliding with a clock net.
- Deferred: multi-unit `-timescale` (this example keeps `ns`); multi-domain with
  `instances` or `subenvs`; per-domain scoreboard latency windows.
