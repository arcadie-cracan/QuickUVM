// Generic-bus register file for the HMAC block.
//
// This REPLACES OpenTitan's `hmac_reg_top` (TL-UL) with a plain single-cycle register
// bus, and replaces `tlul_adapter_sram` (which exposed the message FIFO as a TL-UL
// memory window) with a simple address-decoded write port. It produces exactly the same
// `hmac_reg2hw_t` / `hmac_hw2reg_t` structs, so the vendor RTL above it is UNMODIFIED.
//
// This is the campaign's declared bus normalisation (docs/reproduce_campaign.md §5.1):
// TL-UL is a VIP concern and an explicit non-goal, so it is swapped for a generic bus.
// Every line of the CRYPTO (hmac_core, prim_sha2*) stays vendor-pure.
//
// Register map (byte addresses, 32-bit words):
//   0x00 CFG      RW  [0] hmac_en [1] sha_en [2] endian_swap [3] digest_swap
//                     [4] key_swap [8:5] digest_size [14:9] key_length
//   0x04 CMD      W1P [0] hash_start [1] hash_process [2] hash_stop [3] hash_continue
//   0x08 STATUS   RO  [0] hmac_idle [1] fifo_empty [2] fifo_full [8:3] fifo_depth
//   0x0c WIPE_SECRET W
//   0x10 MSG_LENGTH_LOWER RW
//   0x14 MSG_LENGTH_UPPER RW
//   0x20 + 4i  KEY_i     (i = 0..31)   WO
//   0xa0 + 4i  DIGEST_i  (i = 0..15)   RW  (RW so hash_continue can restore state)
//   0x100..    MSG_FIFO  WO  — any write in this window pushes one message word

module hmac_reg_generic
  import prim_sha2_pkg::*;
  import hmac_reg_pkg::*;
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // Generic register bus
  input  logic [11:0] addr_i,
  input  logic        wr_i,
  input  logic        req_i,
  input  logic [31:0] wdata_i,
  output logic [31:0] rdata_o,

  // Message-FIFO write window (replaces tlul_adapter_sram)
  output logic        msg_fifo_req_o,
  output logic        msg_fifo_we_o,
  output logic [31:0] msg_fifo_wdata_o,
  output logic [31:0] msg_fifo_wmask_o,
  input  logic        msg_fifo_gnt_i,

  output hmac_reg2hw_t reg2hw,
  input  hmac_hw2reg_t hw2reg
);

  localparam logic [11:0] AddrCfg      = 12'h000;
  localparam logic [11:0] AddrCmd      = 12'h004;
  localparam logic [11:0] AddrStatus   = 12'h008;
  localparam logic [11:0] AddrWipe     = 12'h00c;
  localparam logic [11:0] AddrMsgLenLo = 12'h010;
  localparam logic [11:0] AddrMsgLenHi = 12'h014;
  localparam logic [11:0] AddrKeyBase  = 12'h020;   // 32 words -> 0x020..0x09c
  localparam logic [11:0] AddrDigBase  = 12'h0a0;   // 16 words -> 0x0a0..0x0dc
  localparam logic [11:0] AddrFifoBase = 12'h100;   // write window

  // ---- storage -------------------------------------------------------------
  logic [31:0] cfg_q;
  logic [31:0] key_q   [32];
  logic [31:0] dig_q   [16];
  logic [31:0] msglen_lo_q, msglen_hi_q;

  logic in_key, in_dig, in_fifo;
  logic [4:0] key_idx;
  logic [3:0] dig_idx;

  assign in_key  = req_i && (addr_i >= AddrKeyBase) && (addr_i < AddrKeyBase + 12'd128);
  assign in_dig  = req_i && (addr_i >= AddrDigBase) && (addr_i < AddrDigBase + 12'd64);
  assign in_fifo = req_i && (addr_i >= AddrFifoBase);
  assign key_idx = (addr_i - AddrKeyBase) >> 2;
  assign dig_idx = (addr_i - AddrDigBase) >> 2;

  // ---- message FIFO window (the tlul_adapter_sram replacement) -------------
  // A word-aligned bus, so the byte mask is always full — prim_packer (kept from the
  // vendor design) then behaves as a pass-through, and its flush_done still gates
  // hmac_core's hash_process, exactly as upstream.
  assign msg_fifo_req_o   = in_fifo && wr_i;
  assign msg_fifo_we_o    = in_fifo && wr_i;
  assign msg_fifo_wdata_o = wdata_i;
  assign msg_fifo_wmask_o = 32'hffff_ffff;

  // ---- writes --------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      cfg_q       <= '0;
      msglen_lo_q <= '0;
      msglen_hi_q <= '0;
      for (int i = 0; i < 32; i++) key_q[i] <= '0;
      for (int i = 0; i < 16; i++) dig_q[i] <= '0;
    end else begin
      if (req_i && wr_i) begin
        case (addr_i)
          AddrCfg:      cfg_q       <= wdata_i;
          AddrMsgLenLo: msglen_lo_q <= wdata_i;
          AddrMsgLenHi: msglen_hi_q <= wdata_i;
          default: ;
        endcase
        if (in_key) key_q[key_idx] <= wdata_i;
        if (in_dig) dig_q[dig_idx] <= wdata_i;
      end
      // HW digest write-back (the SHA engine updating DIGEST_i)
      for (int i = 0; i < 16; i++) begin
        if (hw2reg.digest[i].d != dig_q[i] && !(req_i && wr_i && in_dig && dig_idx == i[3:0])) begin
          dig_q[i] <= hw2reg.digest[i].d;
        end
      end
      if (hw2reg.msg_length_lower.d != msglen_lo_q) msglen_lo_q <= hw2reg.msg_length_lower.d;
      if (hw2reg.msg_length_upper.d != msglen_hi_q) msglen_hi_q <= hw2reg.msg_length_upper.d;
    end
  end

  // ---- reads ---------------------------------------------------------------
  // REGISTERED read data: a read issued at cycle N returns its data at N+1. This is the
  // ordinary register-block contract, and it is what a generated UVM monitor assumes
  // (sample the request at posedge N, the response at N+1) — so the bench needs no
  // combinational-read workaround.
  logic [31:0] rdata_d;

  always_comb begin
    rdata_d = 32'h0;
    if (req_i && !wr_i) begin
      case (addr_i)
        AddrCfg:      rdata_d = cfg_q;
        AddrStatus:   rdata_d = {23'h0, hw2reg.status.fifo_depth.d,
                                 hw2reg.status.fifo_full.d,
                                 hw2reg.status.fifo_empty.d,
                                 hw2reg.status.hmac_idle.d};
        AddrMsgLenLo: rdata_d = msglen_lo_q;
        AddrMsgLenHi: rdata_d = msglen_hi_q;
        default: ;
      endcase
      if (in_key) rdata_d = key_q[key_idx];
      if (in_dig) rdata_d = dig_q[dig_idx];
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) rdata_o <= 32'h0;
    else         rdata_o <= rdata_d;
  end

  // ---- reg2hw --------------------------------------------------------------
  logic cmd_we;
  assign cmd_we = req_i && wr_i && (addr_i == AddrCmd);

  always_comb begin
    reg2hw = '0;

    reg2hw.cfg.hmac_en.q          = cfg_q[0];
    reg2hw.cfg.sha_en.q           = cfg_q[1];
    reg2hw.cfg.endian_swap.q      = cfg_q[2];
    reg2hw.cfg.digest_swap.q      = cfg_q[3];
    reg2hw.cfg.key_swap.q         = cfg_q[4];
    reg2hw.cfg.digest_size.q      = cfg_q[8:5];
    reg2hw.cfg.key_length.q       = cfg_q[14:9];

    // CMD is write-1-pulse: `qe` is the write strobe, `q` the written bit.
    reg2hw.cmd.hash_start.q       = wdata_i[0];
    reg2hw.cmd.hash_start.qe      = cmd_we;
    reg2hw.cmd.hash_process.q     = wdata_i[1];
    reg2hw.cmd.hash_process.qe    = cmd_we;
    reg2hw.cmd.hash_stop.q        = wdata_i[2];
    reg2hw.cmd.hash_stop.qe       = cmd_we;
    reg2hw.cmd.hash_continue.q    = wdata_i[3];
    reg2hw.cmd.hash_continue.qe   = cmd_we;

    reg2hw.wipe_secret.q          = wdata_i;
    reg2hw.wipe_secret.qe         = req_i && wr_i && (addr_i == AddrWipe);

    for (int i = 0; i < 32; i++) begin
      reg2hw.key[i].q  = key_q[i];
      reg2hw.key[i].qe = req_i && wr_i && in_key && (key_idx == i[4:0]);
    end
    for (int i = 0; i < 16; i++) begin
      reg2hw.digest[i].q  = dig_q[i];
      reg2hw.digest[i].qe = req_i && wr_i && in_dig && (dig_idx == i[3:0]);
    end

    reg2hw.msg_length_lower.q  = msglen_lo_q;
    reg2hw.msg_length_lower.qe = req_i && wr_i && (addr_i == AddrMsgLenLo);
    reg2hw.msg_length_upper.q  = msglen_hi_q;
    reg2hw.msg_length_upper.qe = req_i && wr_i && (addr_i == AddrMsgLenHi);
  end

endmodule
