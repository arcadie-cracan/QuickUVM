# Vendored RTL — OpenTitan (lowRISC), Apache-2.0

These files are copied **unmodified** from [lowRISC/opentitan](https://github.com/lowRISC/opentitan)
(`hw/ip/hmac/rtl/`, `hw/ip/prim/rtl/`). Every file retains its original copyright notice and
`SPDX-License-Identifier: Apache-2.0` header. The full licence text is in `LICENSE`.

They are vendored, not modified, because the campaign's fairness rule
([`docs/reproduce_campaign.md`](../../../../docs/reproduce_campaign.md) §5) requires the DUT's
**crypto core to stay vendor-pure** — only the bus wrapper is ours. That is what makes the
measurement meaningful: any bug here would be a bug we introduced, not a bug in the block.

| file | role |
|---|---|
| `hmac_core.sv`, `hmac_reg_pkg.sv` | the HMAC core + its register struct types |
| `prim_sha2*.sv` | the SHA-2 engine |
| `prim_fifo_sync*.sv`, `prim_packer.sv`, `prim_count*.sv` | message-FIFO plumbing |
| `prim_util_pkg.sv`, `prim_mubi_pkg.sv`, `prim_assert*` | support packages/macros |

The parent directory's `hmac.sv` is a **derivative** of OpenTitan's `hw/ip/hmac/rtl/hmac.sv`
(also Apache-2.0) and states its changes in its header. `hmac_reg_generic.sv` is original work.

Also vendored: `../../dpi/` — OpenTitan's `cryptoc` C golden model (Apache-2.0, from Chromium),
with its own `LICENSE`.
