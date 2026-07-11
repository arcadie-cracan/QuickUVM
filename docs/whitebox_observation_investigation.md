# Whitebox internal-signal observation — industry investigation (K2 Phase 1)

A survey of how UVM environments observe **internal** DUT signals (FSM state, FIFO
levels, internal handshakes) that are invisible at the DUT ports, and the mechanism
chosen for QuickUVM's **K2 whitebox probe** feature. This is the design rationale
behind [`parity_roadmap.md` § K2](parity_roadmap.md) and [`examples/wbx/`](../examples/wbx/).

> **Scope:** OBSERVE-only (never drive). Driving internals (`force`/`deposit`) is a
> narrow fault-injection concern, deliberately out of scope — it makes the TB, not the
> DUT, the source of truth, can mask real bugs, and breaks the black-box contract.

## Terminology

The feature keyword is **`probes`**. "Probe" is the least-ambiguous industry term for
passive observe-only access and collides with nothing. Rejected alternatives:

- **`spy`** — overloaded: Questa/Aldec ship a proprietary *Signal Spy* package
  (`$init_signal_spy`/`signal_force`/`signal_release`) that both mirrors **and**
  force/releases. Naming an observe-only feature "spy" would imply drive capability we
  exclude, and a specific vendor construct we don't use.
- **`peek`** — already the UVM register-backdoor read verb (`uvm_reg::peek`).
- **`tap`** — acceptable synonym, less common in SV/UVM literature.
- **`watchpoint`** — debugger flavor; implies a triggered break, not continuous sampling.

## The three mechanisms

### 1. `bind` (interface/checker into a DUT scope)
Bind an observer interface into a DUT scope; its ports connect to internal nets by
name at the bind point; an `initial` block inside publishes the vif via `config_db`.
The SVA/OVL bound-checker heritage (Cummings SNUG 2009), and OpenTitan's `tb/<ip>_bind.sv`
convention.
- **+** Non-intrusive (separate file); resolves signals *locally* at the bind point
  (more refactor-robust); bind-by-type auto-instruments **every** instance of a module;
  fail-closed at elaboration; IEEE 1800 §23.11.
- **−** Observe-only is a *convention* (bind can `force`); multiple bound instances fire
  the same `config_db::set` key → last-writer-wins clobber; cannot select one parameter
  specialization of a parameterized target; **Verilator supports only bind-to-module-type,
  not bind-to-instance-path**; needs `(module-type, local-signal)` pairs, not a full path.

### 2. XMR (hierarchical `assign`)
`assign probe_if.sig = dut_inst.u_core.fill_level;` in tb_top (or an interface),
republishing an internal net onto an interface field the monitor samples. IEEE 1800 §23.6.
- **+** **The most portable** — the only mechanism that works in Verilator (for public
  signals); **fail-closed at elaboration** (a wrong/renamed path is a hard compile error,
  never a silent miss); reuses QuickUVM's exact `top.sv.j2` vif-publish pattern; matches a
  **"one exact path per net"** data model directly.
- **−** Absolute-path brittleness (spell the full path from the top per signal); generate
  scopes need **named** blocks + const array indices; class scopes can't hold XMR, so the
  interface-republish + `config_db` step is still required.

### 3. `uvm_hdl_read` (DPI/VPI runtime string)
The DPI layer under the register backdoor (`uvm_hdl_read`/`_deposit`/`_force`/`_check_path`).
- **+** Most flexible (runtime string, no recompile); trivial per-instance disambiguation
  by full path; already the register-backdoor door in QuickUVM.
- **− Fail-OPEN** by default — a bad path returns 0 at runtime; silent unless every read is
  check-wrapped. **No Verilator backend** (`UVM_HDL_NO_DPI` → `uvm_fatal`) — kills a free-sim
  CI lane. **Slowest** (DPI + `vpi_handle_by_name` per sample). **Cannot handle `real`** and
  loses type info (flat `uvm_hdl_data_t`). One call from `force`/`deposit`.

## Trade-off table

| Dimension | **XMR** | **bind** | **uvm_hdl_read** |
|---|---|---|---|
| Fail-closed on bad path | ✅ elaboration error | ✅ elaboration error | ❌ fail-open (silent runtime 0) |
| Verilator (free CI) | ✅ (public dotted refs) | ⚠️ module-type only | ❌ no backend |
| Xcelium / Questa / VCS | ✅ (`-access`/`+acc`) | ✅ | ✅ (`-access`) |
| Matches "one exact path per net" | ✅ | ✗ (needs module-type + local name) | ✅ |
| Typed / enum symbolic coverage | ✅ (interface field + `$cast`) | ✅ | ✗ (loses type) |
| `real` signals | ✅ | ✅ | ✗ (logic-vector API only) |
| Multi-instance | one `assign` per const index | type-bind auto-all (one `config_db` key ⇒ clobber) | full-path per instance |
| Perf per sample | native scan (cheapest) | native scan | DPI + string lookup (slowest) |
| Reuses QuickUVM machinery | ✅ exactly (`top.sv.j2` vif publish + K1 SVA) | ✅ + a new bind FileSpec | ✅ (the backdoor door) |

## Decisive factor & recommendation

The textbook default is **bind** — but that assumes a *human* authoring `(module,
signal)` pairs. QuickUVM's consumer (the Architect extension) holds an elaborated model
where **every net has an exact hierarchical path**, and the schema takes plain path
strings relative to the DUT instance. That flips the calculus: **XMR maps the tool's data
model 1:1** (`path` → `assign probe_if.<name> = dut_inst.<path>;`), bind does not, and
`uvm_hdl` shares XMR's path model but is fail-open + Verilator-less.

**Chosen: XMR — a `<dut>_probe_if` fed by hierarchical `assign`s, published via
`config_db`, sampled by a passive probe monitor, with optional in-interface SVA (K1) and
symbolic coverage.**

- **bind** kept as a possible follow-up specifically for "observe **every** instance of a
  repeated sub-block," where type-bind is genuinely superior.
- **uvm_hdl** stays the register-backdoor door only (fail-open + no Verilator disqualify it
  as a general observe primitive).

## Methodology cautions (baked into the generator)

- **Observe-only:** probe fields are interface INPUTS fed by continuous `assign`s; the
  generator never emits `force`/`deposit`, and the observed field is never a driver
  clocking-block output.
- **Sampling clock:** sample through a monitor clocking block (`default input #1step`), not
  raw combinational, for a race-free per-cycle snapshot. Each probe names its clock
  (default = the sole/first); mixed-domain probes are deferred (one clocking block for now).
- **X-prop:** gate probe SVA with `disable iff (!rst_n)` (internal nets are X during reset).
- **Path maintenance:** absolute-path brittleness is the accepted cost of any path-based
  approach — mitigated by the tool regenerating paths on RTL change, and by XMR failing
  *loud* at elaboration rather than silently.

## Deferred (follow-ups)

Multi-clock-domain probes; probes under H1 composition (path prefixing with the per-leaf
`<pathname>_dut`); probes under C3 multi-instantiation; a `bind`-by-type observer for
repeated sub-blocks. Each is rejected fail-closed today with a message pointing here.
