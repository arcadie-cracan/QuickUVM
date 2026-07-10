# mxclk — mixed-unit clocks (M1)

Two clock domains in **different time units**: a fast lane at 500 ps and a slow
lane at 10 ns. Xcelium (like every simulator) takes a single `-timescale`, so
QuickUVM resolves the **finest** unit across the clocks and scales everything into
it.

```
mxclk.yaml
  clock:
    - {name: clk_fast, period: 500, unit: ps}
    - {name: clk_slow, period: 10,  unit: ns}
```

- The finest unit here is **ps**, so the filelist emits `-timescale 1ps/1ps`.
- Each clock's period is scaled into that unit: the fast clkgen is `clkgen #(500)`
  and the slow one `clkgen #(10000)` (10 ns = 10000 ps).
- The clocking-block **drive skew** scales too — the slow lane's `output #2000`
  is 20 % of 10000 ps.
- A scoreboard `max_latency` literal is emitted in its **monitor lane's** own unit.

A single-unit bench is unaffected: the finest unit is that unit, the scale factor
is 1, and every period/skew/timescale is byte-identical to before.

## Run it
```sh
cd sim
xrun -f xrun.f +UVM_TESTNAME=mxclk_test
```
Both lanes' scoreboards (`fast_sb` @500ps, `slow_sb` @10ns) pass **on Xcelium**
(0 errors).

## Scope / notes
- Mixing units requires known SI units (`fs`/`ps`/`ns`/`us`/`ms`/`s`) so the
  scaling is defined — an unknown unit in a mixed set is rejected.
- Deferred: a scoreboard whose two streams are on differently-clocked lanes.
