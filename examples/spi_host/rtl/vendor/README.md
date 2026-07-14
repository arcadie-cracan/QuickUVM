# Vendored from OpenTitan — unmodified

**Upstream:** https://github.com/lowRISC/opentitan (branch `master`)
**Licence:** Apache-2.0 — see `LICENSE` in this directory (verbatim).

Every file here is a **verbatim copy**. Nothing in this directory has been modified.
Sources:

* `hw/ip/spi_host/rtl/` — `spi_host_cmd_pkg`, `spi_host_reg_pkg`, `spi_host_core`,
  `spi_host_fsm`, `spi_host_shift_register`, `spi_host_byte_select`, `spi_host_byte_merge`,
  `spi_host_data_fifos`, `spi_host_command_queue`
* `hw/ip/prim/rtl/` — `prim_util_pkg`, `prim_count_pkg`, `prim_count`, `prim_fifo_sync`,
  `prim_fifo_sync_cnt`, `prim_packer_fifo`, `prim_sparse_fsm_flop`, `prim_sec_anchor_buf`,
  `prim_intr_hw`, `prim_assert`, `prim_flop_macros` and the `prim_assert_*` / `prim_fifo_assert`
  headers
* `hw/ip/prim_generic/rtl/` — `prim_flop`, `prim_flop_en`, `prim_buf`

**28 files, 3,537 lines.** Every line of the SPI PROTOCOL — the FSM (CPOL/CPHA/FULLCYC/CLKDIV,
CS lead/trail/idle, CSAAT), the shift register, the byte packers, the TX/RX/CMD FIFOs, the
per-lane `sd_en_o`, and the gated `sck` — is here, untouched.

## What is NOT here, and why that is the whole argument

`spi_host_reg_top.sv`, `spi_host_window.sv` and OpenTitan's `spi_host.sv` top are **excluded**:
they are the only three files carrying TL-UL, and they are replaced by `../spi_host_reg_generic.sv`
and `../spi_host_ot.sv` (the declared bus normalisation — see the example's README).

**This is checkable, not rhetorical:**

    grep -rl tlul examples/spi_host/rtl/vendor/     # -> nothing

Zero hits across all 28 files. OpenTitan's SPI protocol core has **no bus dependency at all**, so
normalising TL-UL away removes the *configuration* path and nothing else. Everything that makes
`spi_host` hard to verify is above.

Also dropped from the top (they are not part of the protocol): alerts, RACL, and the
`passthrough_i/o` ports — the last of which is typed `spi_device_pkg::passthrough_req_t` and would
drag in the entire `spi_device` IP.
