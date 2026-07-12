// HMAC — a generic-register-bus wrapper around OpenTitan's UNMODIFIED crypto core.
//
// Scope: SHA-256 and HMAC-SHA-256 (docs/reproduce_campaign.md T1). SHA-384/512 and the
// multi-key-length matrix add combinatorics and no architectural insight.
//
// WHAT IS VENDOR (unmodified, from lowRISC/opentitan, Apache-2.0):
//   hmac_core, prim_sha2_32, prim_sha2, prim_sha2_pad, prim_fifo_sync, prim_packer
//   — i.e. every line of the CRYPTO, and the message-FIFO/packer plumbing around it.
//
// WHAT IS OURS (the campaign's declared bus normalisation, §5.1 — TL-UL is a VIP concern
// and an explicit non-goal, so it is swapped for a generic single-cycle register bus):
//   * hmac_reg_generic  replaces  hmac_reg_top        (TL-UL CSRs)
//   * an address-decoded write window replaces tlul_adapter_sram (TL-UL msg-FIFO window)
//   * alert / RACL / interrupt / mubi-idle plumbing is dropped.
//
// prim_packer is DELIBERATELY KEPT even though our bus is word-aligned: its flush_done
// gates hmac_core's hash_process ("trigger after all msg written"), so it is load-bearing
// sequencing, not byte-packing plumbing. Dropping it would mean re-deriving that
// handshake — a self-inflicted DUT bug that would corrupt the experiment.

module hmac
  import prim_sha2_pkg::*;
  import hmac_reg_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  // Generic register bus (replaces TL-UL)
  input  logic [11:0] addr,
  input  logic        wr,
  input  logic        req,
  input  logic [31:0] wdata,
  output logic [31:0] rdata,

  output logic        hmac_done,
  output logic        hmac_idle
);

  hmac_reg2hw_t reg2hw;
  hmac_hw2reg_t hw2reg;

  // ---- message FIFO write path --------------------------------------------
  logic        msg_fifo_req, msg_fifo_we, msg_fifo_gnt;
  logic [31:0] msg_fifo_wdata, msg_fifo_wmask;

  logic        packer_ready, packer_flush_done;
  logic        reg_fifo_wvalid;
  sha_word32_t reg_fifo_wdata;
  logic [31:0] reg_fifo_wmask;

  sha_fifo32_t reg_fifo_wentry, fifo_wdata, fifo_rdata;
  logic        fifo_wvalid, fifo_wready, fifo_rvalid, fifo_rready;
  logic        fifo_full, fifo_empty;
  logic [5:0]  fifo_depth;

  // ---- core <-> sha --------------------------------------------------------
  logic        sha_hash_start, sha_hash_continue, sha_hash_process, sha_hash_done;
  logic        shaf_rvalid, shaf_rready;
  sha_fifo32_t shaf_rdata;
  logic        hmac_fifo_wsel, hmac_fifo_wvalid;
  logic [3:0]  hmac_fifo_wdata_sel;
  logic        reg_hash_done, hmac_core_idle, sha_core_idle, hash_running;
  logic        digest_on_blk;

  sha_word64_t [7:0] digest;
  sha_word64_t [7:0] digest_sw;
  logic        [7:0] digest_sw_we;
  logic [63:0] message_length, sha_message_length;

  logic [1023:0] secret_key;
  logic          sha_en, hmac_en, hash_start, hash_process;
  digest_mode_e  digest_size;
  key_length_e   key_length;

  // ---- config --------------------------------------------------------------
  assign sha_en      = reg2hw.cfg.sha_en.q;
  assign hmac_en     = reg2hw.cfg.hmac_en.q;
  assign digest_size = digest_mode_e'(reg2hw.cfg.digest_size.q);
  assign key_length  = key_length_e'(reg2hw.cfg.key_length.q);

  // CMD is write-1-pulse. (Upstream also gates on cfg_block/invalid_config — SW-error
  // reporting, out of scope here.)
  assign hash_start   = reg2hw.cmd.hash_start.qe   & reg2hw.cmd.hash_start.q   & sha_en;
  assign hash_process = reg2hw.cmd.hash_process.qe & reg2hw.cmd.hash_process.q & sha_en;

  // secret_key[1023:992] = KEY_0 (word 0 is the MOST significant) — upstream ordering.
  always_comb begin
    secret_key = '0;
    for (int i = 0; i < 32; i++) begin
      secret_key[32*i+:32] = reg2hw.key[31-i].q;
    end
  end

  // ---- SW digest write (hash_continue restore); RO in our scope ------------
  always_comb begin
    digest_sw    = '0;
    digest_sw_we = '0;
    for (int i = 0; i < 8; i++) begin
      digest_sw[i]    = {32'b0, reg2hw.digest[i].q};
      digest_sw_we[i] = reg2hw.digest[i].qe;
    end
  end

  // ---- digest readback (SHA-256: lower 32 bits of each word) ---------------
  always_comb begin
    for (int i = 0; i < 16; i++) hw2reg.digest[i].d = '0;
    for (int i = 0; i < 8; i++)  hw2reg.digest[i].d = digest[i][31:0];
  end

  // ---- message length ------------------------------------------------------
  logic        msg_write;
  // message_length is in BITS (what SHA-2 pads with), so this is a straight popcount of
  // the bit-mask — no >>3. And it must be 6 bits: a full 32-bit mask sums to 32, which
  // overflows 5 bits to zero, silently leaving message_length at 0 and making the engine
  // hash a zero-length message.
  logic [$clog2(32+1)-1:0] wmask_ones;
  assign msg_write    = msg_fifo_req & msg_fifo_we;
  assign msg_fifo_gnt = packer_ready;

  always_comb begin
    wmask_ones = '0;
    for (int i = 0; i < 32; i++) wmask_ones = wmask_ones + msg_fifo_wmask[i];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)            message_length <= '0;
    else if (hash_start)   message_length <= '0;
    else if (msg_write && sha_en && packer_ready)
      message_length <= message_length + 64'(wmask_ones);
  end

  // NB `sha_message_length` is DRIVEN BY hmac_core (it adds the inner-hash block for
  // HMAC), and feeds prim_sha2_32. Do not assign it here.
  assign hw2reg.msg_length_lower.d = message_length[31:0];
  assign hw2reg.msg_length_upper.d = message_length[63:32];

  // ---- packer (vendor; endian_swap tied off — the TB feeds big-endian) -----
  prim_packer #(
    .InW (32), .OutW (32), .EnProtection (1'b0)
  ) u_packer (
    .clk_i        (clk),
    .rst_ni       (rst_n),
    .valid_i      (msg_write & sha_en),
    .data_i       (msg_fifo_wdata),
    .mask_i       (msg_fifo_wmask),
    .ready_o      (packer_ready),
    .valid_o      (reg_fifo_wvalid),
    .data_o       (reg_fifo_wdata),
    .mask_o       (reg_fifo_wmask),
    .ready_i      (fifo_wready & ~hmac_fifo_wsel),
    .flush_i      (hash_process),
    .flush_done_o (packer_flush_done),
    .err_o        ()
  );

  // The SHA engine wants big-endian words; upstream always converts here.
  assign reg_fifo_wentry.data = {reg_fifo_wdata[7:0],   reg_fifo_wdata[15:8],
                                 reg_fifo_wdata[23:16], reg_fifo_wdata[31:24]};
  assign reg_fifo_wentry.mask = {reg_fifo_wmask[0],  reg_fifo_wmask[8],
                                 reg_fifo_wmask[16], reg_fifo_wmask[24]};

  assign fifo_wvalid = (hmac_fifo_wsel && fifo_wready) ? hmac_fifo_wvalid : reg_fifo_wvalid;

  // FIFO write mux: message words from the bus, OR the digest fed back by hmac_core for
  // HMAC's OUTER hash (that re-feed is why the core has a FIFO *write* port at all).
  always_comb begin
    fifo_wdata = reg_fifo_wentry;
    if (hmac_fifo_wsel) begin
      fifo_wdata = '{data: digest[hmac_fifo_wdata_sel[2:0]][31:0], mask: '1};
    end
  end

  prim_fifo_sync #(
    .Width       ($bits(sha_fifo32_t)),
    .Pass        (1'b1),
    .Depth       (32),
    .NeverClears (1'b1)
  ) u_msg_fifo (
    .clk_i    (clk),
    .rst_ni   (rst_n),
    .clr_i    (1'b0),
    .wvalid_i (fifo_wvalid & sha_en),
    .wready_o (fifo_wready),
    .wdata_i  (fifo_wdata),
    .depth_o  (fifo_depth),
    .full_o   (fifo_full),
    .rvalid_o (fifo_rvalid),
    .rready_i (fifo_rready),
    .rdata_o  (fifo_rdata),
    .err_o    ()
  );
  assign fifo_empty = (fifo_depth == '0);

  // ---- vendor crypto core --------------------------------------------------
  hmac_core u_hmac (
    .clk_i               (clk),
    .rst_ni              (rst_n),
    .secret_key_i        (secret_key),
    .hmac_en_i           (hmac_en),
    .digest_size_i       (digest_size),
    .key_length_i        (key_length),
    .reg_hash_start_i    (hash_start),
    .reg_hash_stop_i     (1'b0),
    .reg_hash_continue_i (1'b0),
    .reg_hash_process_i  (packer_flush_done),   // after all msg words are written
    .hash_done_o         (reg_hash_done),
    .sha_hash_start_o    (sha_hash_start),
    .sha_hash_continue_o (sha_hash_continue),
    .sha_hash_process_o  (sha_hash_process),
    .sha_hash_done_i     (sha_hash_done),
    .sha_rvalid_o        (shaf_rvalid),
    .sha_rdata_o         (shaf_rdata),
    .sha_rready_i        (shaf_rready),
    .fifo_rvalid_i       (fifo_rvalid),
    .fifo_rdata_i        (fifo_rdata),
    .fifo_rready_o       (fifo_rready),
    .fifo_wsel_o         (hmac_fifo_wsel),
    .fifo_wvalid_o       (hmac_fifo_wvalid),
    .fifo_wdata_sel_o    (hmac_fifo_wdata_sel),
    .fifo_wready_i       (fifo_wready),
    .message_length_i    (message_length),
    .sha_message_length_o(sha_message_length),
    .idle_o              (hmac_core_idle)
  );

  // ---- vendor SHA-2 engine -------------------------------------------------
  prim_sha2_32 #(
    .MultimodeEn (1)
  ) u_sha2 (
    .clk_i            (clk),
    .rst_ni           (rst_n),
    .wipe_secret_i    (1'b0),
    .wipe_v_i         (32'h0),
    .fifo_rvalid_i    (shaf_rvalid),
    .fifo_rdata_i     (shaf_rdata),
    .fifo_rready_o    (shaf_rready),
    .sha_en_i         (sha_en),
    .hash_start_i     (sha_hash_start),
    .hash_stop_i      (1'b0),
    .hash_continue_i  (sha_hash_continue),
    .digest_mode_i    (digest_size),
    .hash_process_i   (sha_hash_process),
    .message_length_i (sha_message_length),
    .digest_i         (digest_sw),
    .digest_we_i      (digest_sw_we),
    .digest_o         (digest),
    .digest_on_blk_o  (digest_on_blk),
    .hash_running_o   (hash_running),
    .hash_done_o      (sha_hash_done),
    .idle_o           (sha_core_idle)
  );

  // ---- status --------------------------------------------------------------
  assign hmac_idle = hmac_core_idle & sha_core_idle & ~hash_running;
  assign hmac_done = reg_hash_done;

  assign hw2reg.status.hmac_idle.d  = hmac_idle;
  assign hw2reg.status.fifo_empty.d = fifo_empty;
  assign hw2reg.status.fifo_full.d  = fifo_full;
  assign hw2reg.status.fifo_depth.d = fifo_depth;

  // unused hw2reg fields
  assign hw2reg.intr_state = '0;
  assign hw2reg.cfg        = '0;
  assign hw2reg.err_code   = '0;
  always_comb for (int i = 0; i < 32; i++) hw2reg.key[i].d = '0;

  // ---- generic register file (replaces hmac_reg_top) ------------------------
  hmac_reg_generic u_reg (
    .clk_i            (clk),
    .rst_ni           (rst_n),
    .addr_i           (addr),
    .wr_i             (wr),
    .req_i            (req),
    .wdata_i          (wdata),
    .rdata_o          (rdata),
    .msg_fifo_req_o   (msg_fifo_req),
    .msg_fifo_we_o    (msg_fifo_we),
    .msg_fifo_wdata_o (msg_fifo_wdata),
    .msg_fifo_wmask_o (msg_fifo_wmask),
    .msg_fifo_gnt_i   (msg_fifo_gnt),
    .reg2hw           (reg2hw),
    .hw2reg           (hw2reg)
  );

endmodule
