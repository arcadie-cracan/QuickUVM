# Filelist generation — format analysis and vendor particularities

Scope: what a QuickUVM-generated **filelist** must contain to serve two very
different consumers — **simulation** (compile + elaborate + run a UVM testbench)
and **coding assistance** (a language server: highlight, complete, go-to-def,
lint) — across the three main vendors (Cadence, Siemens, Synopsys) and,
secondarily, Xilinx/AMD and the open-source toolchain.

This is an analysis to inform the feature, not a design spec. It ends with a
recommendation and one decision that is the user's to make (build vs. delegate).

---

## 0. Executive summary

1. **There is no standard filelist format.** The `.f` "command file" is a
   de-facto convention inherited from Verilog-XL; IEEE 1800 does not define it.
   Every tool has its own dialect, and the divergences are real.

2. **The two consumers want different things from the same file.** A simulator
   needs elaboration switches (`-uvm`, `-timescale`, `-top`, `-access`,
   coverage). A language server needs *only* the source set: files, `+incdir+`,
   `+define+`. Feed a simulator's filelist to an LSP and it either ignores the
   switches (best case) or chokes on them; feed an LSP's file set to a simulator
   and it will not elaborate. This is not hypothetical — `filelistops.ts` in the
   Architect already works around it.

3. **There is a genuinely portable core**: plain source paths, `+incdir+`,
   `+define+`, `-f` nesting, `//`/`#` comments. Every tool listed here — and
   every language server — understands this subset. Everything outside it is
   where the vendors diverge.

4. **The three worst divergences** are (a) **path resolution** of the filelist
   flag (`-f` = relative-to-cwd vs `-F` = relative-to-the-file, supported
   unevenly), (b) **UVM provisioning** (each vendor supplies UVM differently, and
   the open-source tools *cannot run UVM at all*), and (c) **timescale**.

5. **Open-source tools are a coding-assistance and RTL-lint target, not a
   UVM-simulation target.** Verilator and Icarus do not support the UVM class
   library. So "open-source support" for a *UVM generator* means: emit a filelist
   the open-source LSP/lint tools can index, plus (optionally) a Verilator lint
   pass on the DUT — not a runnable UVM bench.

6. **Recommended shape**: one **portable core filelist** (files + `+incdir+` +
   `+define+`, quoted, path-resolution documented) that *both* the LSP configs
   and the per-vendor sim wrappers consume, plus a **thin wrapper per vendor**
   that adds only that vendor's elaboration switches. This is the
   "simple-by-default, powerful-when-needed" answer: one source of truth, N thin
   wrappers. The alternative is to delegate the fan-out to FuseSoC/Edalize or
   Bender (§7) and emit only their input.

---

## 1. Where QuickUVM is today

Grounding, so the recommendation is incremental rather than green-field.

- **Generated, flat layout** — `pkg.f` (package sources), `run.f` (top +
  incdirs + the compile-time switches). Example (`examples/alu/gen/run.f`):

  ```
  -timescale 1ns/1ns
  -f pkg.f
  +incdir+..
  clkgen.sv
  alu.sv
  tb_top.sv
  -y . +libext+.sv
  ```

- **Generated, packaged layout** — chained `*_pkg.f` via `-f`, each with
  `+incdir+.`, resolved from the `gen/` directory.

- **Hand-written, per example** — `sim/xrun.f`, the *real-RTL* Cadence filelist
  the `regress:` block points at (the generated `run.f` compiles a DUT *stub*, so
  it is not the sim filelist). Example:

  ```
  -uvm
  -access +rwc
  -timescale 1ns/1ns
  -linedebug
  -top tb_top
  +incdir+../gen
  ../rtl/alu_pkg.sv
  ../gen/alu_tb_pkg.sv
  ...
  ```

- **VIP chaining** — `from_vip` chains the VIP's `<name>_pkg.f` with Cadence
  **`-F`** (file-relative), so a consumer in another directory resolves it.

**Observations.** (1) The generated filelists are already **Cadence-dialect**
(`-timescale`, `-y . +libext+.sv`, `-F`). (2) There are effectively two
filelists per bench — the generated stub filelist and the hand-written real-RTL
one — and only the latter is a runnable sim filelist. (3) Nothing is emitted for
Siemens/Synopsys/Xilinx/open-source, and nothing is emitted specifically for a
language server. (4) The Architect consumes `.f` through **slang** and had to
add quoting + `+incdir+` handling to make a *simulator* filelist palatable to a
*parser* — which is the whole problem in miniature.

---

## 2. The portable core (the common denominator)

Understood identically by every simulator and every language server surveyed:

| Element | Form | Notes |
|---|---|---|
| Source file | one path per line | absolute, or relative (see §3) |
| Include dir | `+incdir+<dir>` | multiple dirs: repeat, or `+incdir+a+b` (colon on some tools) |
| Macro define | `+define+NAME` / `+define+NAME=VALUE` | value-less and valued both portable |
| Nested filelist | `-f <file>` | universal; `-F` is *not* (see §3) |
| Comment | `// …` or `# …` | both widely accepted; `//` is safest for SV-parsers |
| Line continuation | trailing `\` | accepted by most; avoid — one-arg-per-line is safest |

A filelist restricted to these five lines is the **maximally portable** artifact
and is exactly what a language server wants. Everything below this line is a
divergence.

---

## 3. Divergence #1 — path resolution (the top portability bug)

The single most common cross-tool break. The filelist flag decides whether a
relative path inside the file is resolved against the **current working
directory** (where you invoke the tool) or against the **directory of the
filelist itself**.

| Tool | `-f` (cwd-relative) | `-F` (file-relative) |
|---|---|---|
| Cadence Xcelium | yes | **yes** |
| Synopsys VCS | yes | **yes** |
| Siemens Questa (`vlog`/`qrun`) | yes | recent versions: yes; older: **no** |
| Xilinx Vivado (`xvlog`/`xelab`) | yes | **no** (`-f` only) |
| Verilator | yes | **yes** |
| Icarus (`-c` command file) | cwd | **no** |
| slang (LSP, Architect uses it) | yes | yes (mirrors Cadence) |
| Verible (LSP/lint) | `--file_list_path` + explicit `--file_list_root` | — |

**Consequences.**

- `-F` (file-relative) is the *ergonomic* choice — a filelist is
  location-independent — but it is **not universally available** (Vivado, Icarus,
  old Questa lack it). QuickUVM uses `-F` today only for VIP chaining, which
  therefore silently pins VIP reuse to Cadence/VCS/Verilator.
- `-f` (cwd-relative) is **universal** but forces a documented "run from *this*
  directory" contract. QuickUVM's generated `run.f` already assumes "run from
  `gen/`".
- **Absolute paths** sidestep the whole issue and every tool accepts them, at the
  cost of non-relocatable files (bad for check-in, bad for shared VIP). A
  generator can offer this as a mode.

**Portable rule of thumb:** emit **`-f` with paths relative to a single,
documented invocation directory** (or absolute), and reserve `-F` for the
Cadence/VCS/Verilator-only fast path.

---

## 4. Divergence #2 — UVM provisioning

Each vendor supplies the UVM library its own way, and two open-source tools do
not supply it at all.

| Tool | How UVM enters the compile | Version selection |
|---|---|---|
| Cadence Xcelium | `-uvm` (built-in library auto-added) | `-uvmhome CDNS-1.2` / `-uvm_version` |
| Synopsys VCS | `-ntb_opts uvm` (or `uvm-1.2`) | encoded in the opt |
| Siemens Questa | `-uvm` (built-in), or compile the shipped src (`+incdir+$UVM_HOME/src $UVM_HOME/src/uvm_pkg.sv`) | `-uvmcontrol`, or the chosen src tree |
| Xilinx Vivado xsim | precompiled lib: `xvlog -L uvm`, `xelab -L uvm`, `xsim -L uvm` | Vivado's bundled version only |
| Verilator | **unsupported** — no full UVM (class/constraint/DPI coverage insufficient) | — |
| Icarus | **unsupported** — SV class/constraint support too limited for UVM | — |

**Consequences.**

- The UVM switch is a **wrapper-level** concern, never part of a portable core —
  it differs in spelling *and* mechanism (built-in vs. `-L` precompiled lib vs.
  compile-the-source).
- Vivado's `-L uvm` model is structurally different: UVM is a **pre-mapped
  library**, not a switch, and it must appear at *both* `xvlog`/`xelab` and
  `xsim`. A generator that only knows "add a UVM flag" will get Vivado wrong.
- **Open-source tools cannot run a UVM testbench.** For a UVM generator this is
  the load-bearing fact: Verilator/Icarus are useful here for **DUT lint** and
  for **feeding the language server**, not for running the bench. Framing
  "open-source support" as "runnable UVM sim" would be a wrong goal.

---

## 5. Divergence #3 — timescale, libraries, globbing

- **Timescale.** Command-line spelling differs (`-timescale 1ns/1ps` Cadence /
  Questa / Vivado; `-timescale=1ns/1ps` VCS with `=`; `--timescale` Verilator),
  and elaboration-time resolution is separate again (`vsim -t ps`). QuickUVM
  already computes a single finest-unit `-timescale`; the *value* is portable,
  the *spelling* is per-wrapper. The robust alternative is an in-source
  `` `timescale `` in one dedicated file, which removes it from the filelist
  entirely — worth considering, though it changes generated output.

- **Library mapping.** Cadence/VCS/Verilator work off a flat "compile these
  files" model. **Questa** and **Vivado** are library-oriented: Questa needs
  `vlib work` / `vmap`, Vivado's project mode uses a `.prj` with
  `sv <lib> <file>` lines. In *non-project / command-file* mode both accept `-f`,
  so a generator can avoid `.prj` — but Questa still needs the library created
  before `vlog` runs, which belongs in the wrapper script, not the filelist.

- **Auto-globbing libraries.** `-y <dir> +libext+.sv` (compile-on-demand from a
  library directory) is a Cadence/VCS/Questa feature that **language servers do
  not understand** and that behaves subtly differently per tool. QuickUVM emits
  `-y . +libext+.sv` in `run.f` today; this is exactly the kind of line that must
  *not* appear in the LSP-facing core.

- **Comment syntax for parsers.** `#` comments are common in filelists but are
  **not** SV comments; a language server that naively concatenates filelist lines
  can mis-handle `#`. `//` is the safe choice for a file meant to be read by both.

---

## 6. Per-vendor reference

Compile-time filelist consumption and the invocation model around it. Run-time
args (`+UVM_TESTNAME`, plusargs) are separate and out of the filelist.

### 6.1 Cadence Xcelium
- **Command**: `xrun` (single-call compile+elab+sim) or 3-step
  `xmvlog`/`xmvhdl` → `xmelab` → `xmsim`.
- **Filelist**: `-f` (cwd-relative), `-F` (file-relative), nestable.
- **UVM**: `-uvm`. **Timescale**: `-timescale 1ns/1ps`. **Top**: `-top`.
  **Access/debug**: `-access +rwc`, `-linedebug`.
- **Notes**: the de-facto reference QuickUVM already targets; single-call `xrun`
  is the simplest possible flow. `+libext+`/`-y` supported.

### 6.2 Siemens Questa / ModelSim
- **Command**: 3-step `vlib`/`vmap` → `vlog`/`vcom` → `vsim`, or the unified
  `qrun` (compile+opt+sim in one call, `-f` supported).
- **Filelist**: `vlog -f` (cwd-relative); `-F` in recent Questa.
- **UVM**: `-uvm` (built-in) or compile the shipped source tree. **Timescale**:
  `vlog -timescale` (compile) + `vsim -t` (resolution). **Library**: needs
  `vlib work` first; `-work <lib>`.
- **Notes**: library creation and the `-mfcu` (multi-file compilation unit)
  choice belong in the wrapper. `qrun` narrows the gap to Cadence's single call.

### 6.3 Synopsys VCS
- **Command**: 2-step `vcs` (compile+elab → `simv`) then `./simv`, or `vcs -R`
  to run immediately.
- **Filelist**: `-f` (cwd-relative), `-F` (file-relative). `-file` for a
  richer command file.
- **UVM**: `-ntb_opts uvm` / `-ntb_opts uvm-1.2`. **Timescale**:
  `-timescale=1ns/1ps` (note the `=`). **SV**: `-sverilog` / `-full64`.
  **Access**: `-debug_access+all`.
- **Notes**: the `=` in `-timescale=` and the `-ntb_opts` spelling are the two
  gotchas versus Cadence.

### 6.4 Xilinx / AMD Vivado (xsim)
- **Command**: 3-step `xvlog`/`xvhdl` → `xelab` → `xsim`, or project-mode `.prj`.
- **Filelist**: `xvlog -f` / `xelab -f` (cwd-relative, **no `-F`**). Project
  mode uses a **`.prj`** with per-file lines: `sv work file.sv` /
  `verilog work file.v` / `vhdl work file.vhd` — a *different format*.
- **UVM**: precompiled library, `-L uvm` at `xvlog`, `xelab`, **and** `xsim`.
  **Timescale**: `xelab -timescale`.
- **Notes**: the only surveyed tool with a genuinely different filelist format
  (`.prj`) *and* a library-not-switch UVM model. A `-f` command-file path avoids
  the `.prj`, but `-L uvm` must still thread through three commands.

### 6.5 Verilator (open source)
- **Command**: `verilator --binary`/`--cc` (verilate → C++ → build → run).
- **Filelist**: `-f` (cwd-relative), `-F` (file-relative). `.vc` files are the
  same format.
- **UVM**: **not supported.** **Timescale**: `--timescale` /
  `--timescale-override`.
- **Notes**: excellent for **DUT lint** (`--lint-only`) and 2-state RTL sim;
  irrelevant for running the UVM TB. Its `-f`/`-F` semantics match Cadence, so a
  Cadence-style core is directly reusable for a lint pass.

### 6.6 Icarus Verilog (open source)
- **Command**: `iverilog` → `vvp`.
- **Filelist**: `-c <cmdfile>` (command file: files + `+incdir+`/`+libdir+`/`-y`,
  cwd-relative). Note `-f` in Icarus means something else (a code-generator flag).
- **UVM**: **not supported.** **Timescale**: in-source `` `timescale ``.
- **Notes**: the flag-name difference (`-c`, not `-f`) is the trap. Useful only
  for small non-UVM RTL.

---

## 7. Coding-assistance consumers

What the popular SystemVerilog language servers / lint tools actually read. The
convergence: **most either eat a `.f` directly or want a config that points at
one**, so a clean portable `.f` covers the field, and for the config-based tools
the generator can emit that config too.

| Tool | Consumes | Filelist-native? |
|---|---|---|
| **slang** (Architect uses it) | `-f`/`-F` command files | **yes** — this is why the Architect chose it |
| **Verible** (`verible-verilog-ls`, `-lint`, `-format`) | `--file_list_path` + `--file_list_root` | **yes** (plain list + `+incdir+`) |
| **svlangserver** (VS Code "SystemVerilog - Language Server") | `systemverilog.includeIndexing` globs + `libraryIndexing` | no — glob config, not `.f` |
| **veridian** | `veridian.yaml` (source dirs, include dirs) or auto | partial — its own YAML |
| **svls** | `.svls.toml` | no — TOML |
| **DVT Eclipse** (AMIQ) | `.f` via `+dvt_init+` + build config | **yes** — the most `.f`-native |
| **Sigasi** | project / filelist import | partial |

**Takeaways.**
- A **quoted, portable `.f`** (files + `+incdir+` + `+define+`, no
  `-uvm`/`-timescale`/`-y`) is consumable by slang, Verible and DVT directly, and
  is the safest thing to hand any parser. This is the artifact to make
  first-class.
- For the config-based tools (svlangserver globs, veridian/svls TOML), the
  generator can additionally emit that small config, all pointing back at the
  same source set — but that is a convenience layer, not the core.
- The Architect's existing `filelistops.ts` quoting (`+incdir+"path"`, full-path
  quoting for space-safety, `//`/`#` comment skipping) is precisely the
  transform that makes a `.f` LSP-safe, and is prior art to reuse.

---

## 8. Prior art (build vs. delegate)

Two mature tools already do the exact vendor fan-out. QuickUVM can *emit their
input* instead of hand-rolling per-vendor wrappers.

- **FuseSoC + Edalize.** A `.core` (YAML) describes sources + filesets;
  **Edalize** backends generate ready-to-run scripts/filelists for Xcelium, VCS,
  Questa/ModelSim, Vivado (xsim), Verilator, Icarus, and more. This *is* the
  multi-vendor filelist generator the feature asks for. Trade-off: a Python dep
  and a `.core` format users must learn; UVM support quality varies by backend.
- **Bender** (PULP) — already in QuickUVM's world. `bender script <tool>` emits
  per-tool filelists (`vsim`, `vcs`, `flist`, …) from a `Bender.yml`. Narrower
  vendor set than Edalize, but zero new concepts for a bench that already uses
  Bender.
- **No IEEE/Accellera standard** exists to target — so "generate the standard
  format" is not an option; the choice is genuinely "our thin wrappers" vs.
  "emit a `.core`/`Bender.yml` and delegate".

---

## 9. Recommendation

A **layered filelist model**, incremental over what QuickUVM emits today:

1. **Portable core filelist** — `<name>.f` (or `compile.f`): *only* source paths
   + `+incdir+` + `+define+`, quoted for space-safety, `//` comments, a single
   documented path-resolution contract (cwd-relative `-f`, or an
   absolute-path mode). This is the LSP-facing artifact **and** the shared input
   to every sim wrapper. It is `run.f` minus the Cadence switches.

2. **Thin per-vendor sim wrappers** — one small file each that `-f`s the core and
   adds *only* that vendor's elaboration switches:
   - `xrun.f` (Cadence): `-uvm -timescale … -top … -access +rwc -f <core>.f`
   - `vcs.f` (Synopsys): `-ntb_opts uvm -timescale=… -f <core>.f` (+ `simv` note)
   - `questa` (Siemens): a `.do`/`qrun` wrapper (needs `vlib work` first) `-f <core>.f`
   - `vivado` (Xilinx): `xvlog/xelab -L uvm -f <core>.f` (thread `-L uvm` through 3 calls)
   - `verilator.vc` (open source): **lint-only** on the DUT subset, no UVM
   The wrappers are where all §3–§5 divergence lives; the core stays clean.

3. **Optional LSP configs** — point svlangserver/veridian/Verible at the core.
   Nice-to-have, not the core.

**The decision that is yours:** own the wrappers (full control, N vendor dialects
to maintain and keep current as tools change) **or** emit a FuseSoC `.core` /
`Bender.yml` and delegate the fan-out (less to maintain, adds a tool dependency
and a config users must adopt). A middle path — emit the **portable core**
ourselves (it is the single point every consumer needs and the LSP story that
nothing else gives you) and offer **both** a couple of hand-owned wrappers
(Cadence first, since it is proven) *and* an optional `.core` for the long tail —
is likely the best value/effort, and matches "simple by default, powerful when
needed."

**Suggested first slice** (highest leverage, lowest risk): split today's
Cadence-flavoured `run.f` into (a) a clean portable **core** and (b) a Cadence
**wrapper** that adds the switches. That immediately (1) gives the Architect an
LSP-clean filelist to index instead of one it has to sanitise, and (2) makes
every subsequent vendor a ~10-line wrapper rather than a fork of `run.f`.

---

## 10. Decision and what was built (opt-in `sim:` block)

Direction chosen: **portable core + owned thin wrappers** for the three main
vendors (provable against the installed simulators), with **Bender** as the
long-tail / composable-package option. The core is `compile.f`; the wrappers are
thin **run scripts** (not filelists — see the two findings below that forced
that). Opt-in via a `sim:` block; absent ⇒ byte-identical.

```yaml
sim:
  tools: [xcelium, vcs, questa]   # which vendor run scripts to emit
  rtl_filelist: ../rtl/dut.f      # the real DUT RTL (referenced; paths RUN-DIR-relative)
```

Emitted into `gen/`: `compile.f` (portable core) + `sim_xcelium.sh` /
`sim_vcs.sh` / `sim_questa.sh`.

Also emits, when `bender: true`, a **`Bender.yml`** — the bench as a composable
Bender package. Bender needs file *paths* (not a `-f` reference), so the
referenced RTL filelist is read and inlined; `bender script <target>` then fans
out to `vsim` / `vcs` / `verilator` / `vivado(-sim)` / `flist(-plus)` (no native
Xcelium target — use `sim_xcelium.sh`). UVM library flags are added by the
consuming flow, not by Bender.

### Validated (examples/reqrsp, a clocked bench)

- **Cadence** (`xrun`): **green** — 0 UVM_ERROR, 30/30 PASSED.
- **Questa** (`qrun`): **green** — 0 UVM_ERROR, 30/30 PASSED.
- **VCS** (`vcs`): **green** — 0 UVM_ERROR, 30/30 PASSED (the two-step
  `vcs` compile → `./simv` run).
- **Bender** (`bender 0.32.1`): the generated `Bender.yml` parses and fans out
  (`flist-plus` / `vsim` / `vcs` / `verilator` all OK); `bender script
  flist-plus` piped to `xrun` runs **green** (30/30 PASSED) — the manifest is a
  complete, correct source set.
- **Coding assistance**: `verible-verilog-project` builds a symbol table directly
  from `compile.f` (nested `-f`, `+incdir+` and all) — the go-to-def / completion
  foundation. slang consumes the same `-f` form (it is what the Architect uses).

### Findings that shaped the design (each cost a real run)

1. **`-F` is not portable — it fails on qrun.** The core first referenced the RTL
   with Cadence-style `-F` (file-relative). xrun resolved it; **qrun resolved the
   *first* RTL file to an absolute path and left the *second* relative**, so it
   silently compiled the generated DUT *stub* (`gen/<dut>.sv`) instead of the real
   RTL → the DUT drove all-zeros → 1002 scoreboard mismatches. Fix: reference the
   RTL with plain **`-f`** (universal cwd-relative) and require its paths to be
   run-dir-relative (the `regress.filelist` convention). This is §3's top trap,
   caught by construction.

2. **VCS rejects `-ntb_opts uvm` inside a `-f` file** (`Error-[NS-NTB_F]`). It must
   be on the command line. That alone rules out a pure per-vendor *filelist* for
   VCS and is why the wrappers are **run scripts**, which also cleanly carry VCS's
   two-step `vcs → ./simv` and any Questa library setup.

3. **The example choice matters for the runtime proof.** A *combinational* DUT
   (examples/alu) shows a first-cycle sampling race on Questa (1 mismatch at t=5)
   that Cadence's scheduler masks — a **testbench-timing** portability issue, not a
   filelist one (the filelist compiled the right RTL). The green-on-vendors proof
   therefore ships on a **clocked** example (reqrsp), whose sampling is
   deterministic across simulators. The combinational first-cycle race is a
   separate, real finding worth its own look (monitor sampling skew).

### Deferred

An LSP-config emitter for the config-based servers (svlangserver/veridian),
`Bender.yml` under the **packaged** layout (its multi-package source graph — flat
is supported and validated), and Xilinx/Verilator/Icarus wrappers (open-source =
lint + LSP only, no UVM).
