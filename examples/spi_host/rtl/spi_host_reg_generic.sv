// OURS — the declared bus normalisation. Replaces OpenTitan's `spi_host_reg_top.sv` (the
// TL-UL CSRs) and `spi_host_window.sv` (which is nothing but two TL-UL SRAM adapters for
// the TX/RX FIFO windows).
//
// Derived from OpenTitan's spi_host register description (Apache-2.0). Statement of changes
// (Apache-2.0 §4(b)): the TL-UL interface is replaced with a generic single-cycle register
// bus; the TL-UL RXDATA/TXDATA windows are absorbed into that same bus; alerts, RACL and the
// `passthrough_i/o` ports are dropped (the last is typed `spi_device_pkg::passthrough_req_t`
// and would pull in the entire spi_device IP). The CSR MAP and the FIELD SEMANTICS are
// reproduced faithfully — they are what the bench actually programs.
//
// The bus under test is SPI, not TL-UL. Nothing below the SPI protocol is touched.
`timescale 1ns/1ns

module spi_host_reg_generic
  import spi_host_cmd_pkg::*;
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // generic single-cycle register bus. rdata is REGISTERED: request at N, data at N+1.
  input  logic [5:0]  addr_i,
  input  logic        req_i,
  input  logic        wr_i,
  input  logic [3:0]  be_i,
  input  logic [31:0] wdata_i,
  output logic [31:0] rdata_o,

  // --- to the core ---------------------------------------------------------------
  output logic        en_o,          // CONTROL.SPIEN
  output logic        sw_rst_o,      // CONTROL.SW_RST
  output logic        output_en_o,   // CONTROL.OUTPUT_EN -- gates EVERY SPI output
  output command_t    command_o,
  output logic        command_valid_o,
  input  logic        command_ready_i,

  // TX window (a write to TXDATA pushes)
  output logic [31:0] tx_data_o,
  output logic [3:0]  tx_be_o,
  output logic        tx_valid_o,
  input  logic        tx_ready_i,

  // RX window (a read of RXDATA POPS -- a destructive read)
  input  logic [31:0] rx_data_i,
  input  logic        rx_valid_i,
  output logic        rx_ready_o,

  // status from the core
  input  logic        rx_stall_i,
  input  logic        tx_stall_i,
  input  logic        active_i
);

  // The register map (offsets are OpenTitan's, verbatim).
  localparam bit [5:0] ADDR_INTR_STATE   = 6'h00;
  localparam bit [5:0] ADDR_INTR_ENABLE  = 6'h04;
  localparam bit [5:0] ADDR_CONTROL      = 6'h10;
  localparam bit [5:0] ADDR_STATUS       = 6'h14;
  localparam bit [5:0] ADDR_CONFIGOPTS   = 6'h18;
  localparam bit [5:0] ADDR_CSID         = 6'h1c;
  localparam bit [5:0] ADDR_COMMAND      = 6'h20;
  localparam bit [5:0] ADDR_RXDATA       = 6'h24;   // window, destructive read
  localparam bit [5:0] ADDR_TXDATA       = 6'h28;   // window
  localparam bit [5:0] ADDR_ERROR_STATUS = 6'h30;

  logic [31:0] control_q, configopts_q, csid_q, error_status_q;
  logic [31:0] intr_state_q, intr_enable_q;

  wire wr_hit = req_i && wr_i;
  wire rd_hit = req_i && !wr_i;

  //--------------------------------------------------------------------------------
  // CONTROL. **OUTPUT_EN resets to 0.** It gates sck, csb and every sd lane, so a DUT
  // out of reset drives NOTHING -- and with pull-ups on the bus that silence looks
  // perfectly quiet and legal. A sequence that forgets to set it produces a bench that
  // runs, sees no error, and tests nothing. That is the mutation this bench must survive.
  //--------------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) control_q <= 32'h0000_007f;   // watermarks default; SPIEN/OUTPUT_EN = 0
    else if (wr_hit && addr_i == ADDR_CONTROL) control_q <= wdata_i;
  end
  assign en_o        = control_q[31];   // SPIEN
  assign sw_rst_o    = control_q[30];
  assign output_en_o = control_q[29];

  //--------------------------------------------------------------------------------
  // CONFIGOPTS -- cpol / cpha / fullcyc / csn lead-trail-idle / clkdiv.
  // NB SCALAR on this revision of the IP, not a per-CS multireg.
  //--------------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) configopts_q <= '0;
    else if (wr_hit && addr_i == ADDR_CONFIGOPTS) configopts_q <= wdata_i;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) csid_q <= '0;
    else if (wr_hit && addr_i == ADDR_CSID) csid_q <= wdata_i;
  end

  //--------------------------------------------------------------------------------
  // COMMAND -- hwext + hwqe upstream: it has NO STORAGE. The command launches on the
  // WRITE STROBE, never on a value:
  //
  //     assign command_valid = |cmd_qes;      // spi_host.sv, vendor
  //
  // Drive `command_valid_o` from a value (or forget the strobe entirely) and NO command
  // ever issues: the DUT sits idle, the bus stays quiet, nothing errors, and the bench
  // passes by doing nothing.
  //--------------------------------------------------------------------------------
  assign command_valid_o = wr_hit && (addr_i == ADDR_COMMAND);

  always_comb begin
    command_o                    = '0;
    // segment (COMMAND)
    command_o.segment.len        = wdata_i[19:0];
    command_o.segment.csaat      = wdata_i[20];
    command_o.segment.speed      = wdata_i[22:21];
    // DIRECTION decodes to the core's two enables: Dummy=0, RdOnly=1, WrOnly=2, Bidir=3.
    command_o.segment.cmd_rd_en  = wdata_i[23];   // direction[0]
    command_o.segment.cmd_wr_en  = wdata_i[24];   // direction[1]
    // configopts (a separate register -- the core takes them together as one command_t)
    command_o.configopts.clkdiv   = configopts_q[15:0];
    command_o.configopts.csnidle  = configopts_q[19:16];
    command_o.configopts.csntrail = configopts_q[23:20];
    command_o.configopts.csnlead  = configopts_q[27:24];
    command_o.configopts.full_cyc = configopts_q[29];
    command_o.configopts.cpha     = configopts_q[30];
    command_o.configopts.cpol     = configopts_q[31];
  end

  //--------------------------------------------------------------------------------
  // TXDATA window -- a write pushes into the TX FIFO. The byte enables select which
  // bytes of the word are real, so a partial word is legal.
  //--------------------------------------------------------------------------------
  assign tx_valid_o = wr_hit && (addr_i == ADDR_TXDATA);
  assign tx_data_o  = wdata_i;
  assign tx_be_o    = be_i;

  //--------------------------------------------------------------------------------
  // RXDATA window -- a READ POPS the FIFO. Destructive: read it twice and the second
  // read returns the NEXT word, not the same one.
  //--------------------------------------------------------------------------------
  assign rx_ready_o = rd_hit && (addr_i == ADDR_RXDATA) && rx_valid_i;

  //--------------------------------------------------------------------------------
  // STATUS (read-only, hardware-driven).
  //--------------------------------------------------------------------------------
  logic [31:0] status;
  always_comb begin
    status      = '0;
    status[31]  = command_ready_i;   // READY: the command queue can take a command
    status[30]  = active_i;
    status[27]  = tx_stall_i;
    status[23]  = rx_stall_i;
    status[24]  = ~rx_valid_i;       // RXEMPTY
  end

  //--------------------------------------------------------------------------------
  // ERROR_STATUS -- W1C.
  //--------------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) error_status_q <= '0;
    else if (wr_hit && addr_i == ADDR_ERROR_STATUS)
      error_status_q <= error_status_q & ~wdata_i;   // write-1-to-clear
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      intr_state_q  <= '0;
      intr_enable_q <= '0;
    end else begin
      if (wr_hit && addr_i == ADDR_INTR_STATE)  intr_state_q  <= intr_state_q & ~wdata_i;
      if (wr_hit && addr_i == ADDR_INTR_ENABLE) intr_enable_q <= wdata_i;
    end
  end

  //--------------------------------------------------------------------------------
  // Read data. REGISTERED -- request at N, data at N+1 (the same contract hmac's
  // generic bus uses, and what the generated register agent expects).
  //--------------------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) rdata_o <= '0;
    else if (rd_hit) begin
      case (addr_i)
        ADDR_INTR_STATE:   rdata_o <= intr_state_q;
        ADDR_INTR_ENABLE:  rdata_o <= intr_enable_q;
        ADDR_CONTROL:      rdata_o <= control_q;
        ADDR_STATUS:       rdata_o <= status;
        ADDR_CONFIGOPTS:   rdata_o <= configopts_q;
        ADDR_CSID:         rdata_o <= csid_q;
        ADDR_RXDATA:       rdata_o <= rx_data_i;    // and pops (rx_ready_o above)
        ADDR_ERROR_STATUS: rdata_o <= error_status_q;
        default:           rdata_o <= '0;
      endcase
    end
  end

endmodule
