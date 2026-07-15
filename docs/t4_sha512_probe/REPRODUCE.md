# T4 SHA512 probe — the HVL half, generated and elaborated

Evidence for [`../t4_caliptra_sha512_assessment.md`](../t4_caliptra_sha512_assessment.md). Reproduces
the QuickUVM equivalent of Caliptra's UVMF SHA512 **HVL half**, and proves the file-reading golden
model drops into the K0 predictor seam. All on Xcelium 25.09.

`sha512.yaml` mirrors the real UVMF source (`SHA512_interface_cfg.yaml` / `SHA512_env_cfg.yaml`): the
`op` enum + its values, `test_case_sel`, the 512-bit `result`, active-high reset, and two agents (an
AHB-driving initiator + a passive monitor-split) feeding one predictor+scoreboard.

## 1. Generate the HVL half (32 files, clean)

    quick-uvm generate -c sha512.yaml -o gen --no-backup      # 32 created

Refutations, verifiable in the output:

    grep -n 'typedef enum\|op inside' gen/sha_in_item.svh     # op_e enum + constraint  (hdl_typedef REFUTED)
    grep -n 'connect' gen/sha512_env.svh gen/sha512_scoreboard.svh   # 3 TLM edges from one line (tlm_connections REFUTED)

## 2. Fill the predictor with the ported NIST-file golden model

Paste the two blocks in [`predictor_paste.sv`](predictor_paste.sv) into their matching pragma
regions — the `class_item_additional` block into `gen/sha512_predictor.svh`, the `prediction_logic`
block into `gen/sha512_reference_model.svh`. It is a faithful port of Caliptra's real
`SHA512_predictor.svh`: `$fopen`/`$fgets`/`$sscanf` on a NIST `.rsp` vector, then a left-align shift.
**No `$system`, no Python, no DPI** — the campaign's "shells out to Python" premise was factually
wrong (the real predictor uses plain SV file I/O).

## 3. Prove idempotent regeneration (the code-preservation contract, the axis under test)

    cp -r gen gen.bak
    quick-uvm generate -c sha512.yaml -o gen --no-backup      # 0 updated, 32 unchanged
    diff -rq gen.bak gen                                       # IDENTICAL

The ported predictor survives regeneration byte-identical — the same `// pragma custom` contract
UVMF has, exercised with real domain code, not an empty stub.

## 4. Prove it elaborates on Xcelium

    xrun -uvm -f gen/run.f -elaborate      # 0 errors

The pasted `$fopen`/`$fgets`/`$sscanf` predictor is valid SV in the seam. (One edit while porting:
the enum type is QuickUVM's `op_e`, not UVMF's `sha512_in_op_transactions` — reflected in the paste.)

## What this proves — and does NOT

**Proves [C]:** the HVL half generates clean and elaborates; the op enum / constraint / TLM edges
render; the file-reading golden model expresses in the K0 seam, compiles, and survives idempotent
regeneration — *easier* than HMAC's DPI-C library because it is native SV I/O.

**Does not prove:** correct SHA512 digests against a DUT. There is no SHA512 RTL here and no NIST
`.rsp` files are committed — the comparison is architectural (HVL parity), per the campaign. The
predictor claim is "the seam expresses and compiles the golden model," not "it computes right."
