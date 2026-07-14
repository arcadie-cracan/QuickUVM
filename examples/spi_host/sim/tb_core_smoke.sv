// SLICE 0a — "hello, one SPI byte" against OpenTitan's spi_host_core. NO UVM, NO register
// block, NO wrapper.
//
// This exists to separate two risks that Slice 0 would otherwise conflate:
//   (a) do we understand this DUT?           <- answered here, with zero wrapper risk
//   (b) is our generic register block right?  <- Slice 0b
//
// T1's lesson: validate the DUT with a directed RTL smoke test BEFORE building the bench.
// It caught a real bug there (a byte-enable sum overflowing to zero, so the DUT hashed a
// zero-length message while the bench looked fine).
//
// The TB plays a dumb SPI device: it drives MISO (sd[1]) on the falling edge of sck and
// samples MOSI (sd[0]) on the rising edge — standard mode 0, full duplex.
`timescale 1ns/1ns

module tb_core_smoke;

  import spi_host_cmd_pkg::*;

  localparam int unsigned CLKDIV   = 4;
  localparam bit [7:0]    HOST_TX  = 8'hA5;   // what the host sends us
  localparam bit [7:0]    DEV_TX   = 8'h3C;   // what we send the host

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;

  // core <-> TB
  command_t    command;
  logic        command_valid, command_ready;
  logic        en;
  logic [31:0] tx_data;
  logic [3:0]  tx_be;
  logic        tx_valid, tx_ready, tx_byte_select_full;
  logic [31:0] rx_data;
  logic        rx_valid, rx_ready;
  logic        sw_rst;
  logic        sck, csb;
  logic [3:0]  sd_o, sd_en, sd_i;
  logic        rx_stall, tx_stall, active;

  spi_host_core #(.NumCS(1)) dut (
    .clk_i(clk), .rst_ni(rst_n),
    .command_i(command), .command_csid_i(1'b0),
    .command_valid_i(command_valid), .command_ready_o(command_ready),
    .en_i(en),
    .tx_data_i(tx_data), .tx_be_i(tx_be), .tx_valid_i(tx_valid),
    .tx_ready_o(tx_ready), .tx_byte_select_full_o(tx_byte_select_full),
    .rx_data_o(rx_data), .rx_valid_o(rx_valid), .rx_ready_i(rx_ready),
    .sw_rst_i(sw_rst),
    .sck_o(sck), .csb_o(csb), .sd_o(sd_o), .sd_en_o(sd_en), .sd_i(sd_i),
    .rx_stall_o(rx_stall), .tx_stall_o(tx_stall), .active_o(active)
  );

  //--------------------------------------------------------------------------
  // The dumb SPI device (mode 0). It drives MISO on the FALLING edge so the value
  // is stable when the host samples it on the RISING edge — and the first bit must
  // be on the wire before any edge exists, which is the whole reason `respond:
  // prefetch` had to be built.
  //--------------------------------------------------------------------------
  logic [7:0] dev_shift_tx, dev_rx;
  int         dev_bits;
  logic       dev_miso;

  assign sd_i[0] = 1'b1;          // MOSI is DUT-driven; the device does not drive lane 0
  assign sd_i[1] = dev_miso;      // MISO — the device owns lane 1
  assign sd_i[2] = 1'b1;
  assign sd_i[3] = 1'b1;

  initial begin
    dev_miso = 1'b1;
    dev_bits = 0;
    dev_rx   = '0;
    @(negedge csb);
    dev_shift_tx = DEV_TX;
    dev_miso     = DEV_TX[7];    // bit 7 out BEFORE the first sck edge
    forever begin
      @(posedge sck);            // the host samples MISO here; we sample MOSI here
      dev_rx   = {dev_rx[6:0], sd_o[0]};
      dev_bits = dev_bits + 1;
      @(negedge sck);            // ...and we change MISO here
      dev_shift_tx = {dev_shift_tx[6:0], 1'b0};
      dev_miso     = dev_shift_tx[7];
    end
  end

  //--------------------------------------------------------------------------
  // Measure sck: its period must be 2*(CLKDIV+1) core clocks. If it is not, our
  // understanding of the divider is wrong and every later timing claim is void.
  //--------------------------------------------------------------------------
  time t_sck_a, t_sck_b;
  int  sck_edges = 0;
  always @(posedge sck) begin
    if (sck_edges == 0) t_sck_a = $time;
    if (sck_edges == 1) t_sck_b = $time;
    sck_edges++;
  end

  //--------------------------------------------------------------------------
  int errors = 0;
  logic [31:0] rx_captured;   // latch it AT the handshake — rx_data is stale after the pop
  task automatic chk(input bit ok, input string what);
    if (ok) $display("  PASS  %s", what);
    else begin
      $display("  FAIL  %s", what);
      errors++;
    end
  endtask

  initial begin
    command      = '0;
    command_valid = 1'b0;
    en            = 1'b0;
    tx_data       = '0;
    tx_be         = '0;
    tx_valid      = 1'b0;
    rx_ready      = 1'b0;
    sw_rst        = 1'b0;

    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (4) @(posedge clk);

    en = 1'b1;                     // CONTROL.spien

    // --- push one byte into the TX fifo ---
    tx_data  = {24'h0, HOST_TX};
    tx_be    = 4'b0001;            // one valid byte
    tx_valid = 1'b1;
    do @(posedge clk); while (!tx_ready);
    tx_valid = 1'b0;

    // --- issue the command: 1 byte, Standard, Bidir (full duplex) ---
    command.configopts.clkdiv   = 16'(CLKDIV);
    command.configopts.csnidle  = 4'd2;
    command.configopts.csnlead  = 4'd2;
    command.configopts.csntrail = 4'd2;
    command.configopts.full_cyc = 1'b0;
    command.configopts.cpha     = 1'b0;
    command.configopts.cpol     = 1'b0;
    command.segment.speed       = Standard;
    command.segment.cmd_wr_en   = 1'b1;   // Bidir = write AND read
    command.segment.cmd_rd_en   = 1'b1;
    command.segment.len         = 20'd0;  // len is bytes-1 => one byte
    command.segment.csaat       = 1'b0;

    command_valid = 1'b1;
    do @(posedge clk); while (!command_ready);
    command_valid = 1'b0;

    // --- wait for the received byte ---
    fork
      begin
        do @(posedge clk); while (!rx_valid);
        rx_captured = rx_data;     // capture WHILE valid, before the pop
        rx_ready    = 1'b1;
        @(posedge clk);
        rx_ready    = 1'b0;
      end
      begin
        repeat (2000) @(posedge clk);
        $display("  FAIL  timeout: rx_valid never asserted");
        errors++;
      end
    join_any
    disable fork;

    repeat (20) @(posedge clk);

    $display("\n=== SLICE 0a: one SPI byte through OpenTitan's spi_host_core ===");
    chk(sck_edges >= 8, $sformatf("sck toggled (%0d rising edges, expect >= 8)", sck_edges));
    chk((t_sck_b - t_sck_a) == 2 * (CLKDIV + 1) * 10,
        $sformatf("sck period == 2*(CLKDIV+1) core clocks (got %0t, expect %0t)",
                  t_sck_b - t_sck_a, 2 * (CLKDIV + 1) * 10));
    chk(dev_bits >= 8, $sformatf("the device saw 8 sck edges (%0d)", dev_bits));
    chk(dev_rx == HOST_TX,
        $sformatf("the device received the host's byte: got %02h, expect %02h",
                  dev_rx, HOST_TX));
    chk(rx_captured[7:0] == DEV_TX,
        $sformatf("the host received the device's byte: got %02h, expect %02h",
                  rx_captured[7:0], DEV_TX));
    chk(!rx_stall && !tx_stall, "no stall");

    if (errors == 0) $display("\n*** SLICE 0a PASSED ***\n");
    else             $display("\n*** SLICE 0a FAILED (%0d) ***\n", errors);
    $finish;
  end

endmodule
