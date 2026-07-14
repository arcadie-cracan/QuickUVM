// SLICE 0b — the same "one SPI byte", but driven through the REGISTER BUS, on the real
// tri-state pad ring. This is what validates `spi_host_reg_generic.sv` — the riskiest file
// in this example, and the only one we wrote.
//
// Slice 0a proved we understand the DUT. This proves we understand the REGISTER INTERFACE,
// with the DUT already known-good, so a failure here can only be the wrapper.
//
// Two traps live in here, and this test exists to fall into them if we got them wrong:
//   * COMMAND launches on the WRITE STROBE, not on a value.
//   * CONTROL.OUTPUT_EN resets to 0 and gates every output. Forget it and the DUT drives
//     nothing, the pull-ups make the bus look quiet and legal, and the bench passes by
//     doing nothing.
`timescale 1ns/1ns

module tb_reg_smoke;

  localparam int unsigned CLKDIV  = 4;
  localparam bit [7:0]    HOST_TX = 8'hA5;
  localparam bit [7:0]    DEV_TX  = 8'h3C;

  // register offsets
  localparam bit [5:0] CONTROL    = 6'h10;
  localparam bit [5:0] STATUS     = 6'h14;
  localparam bit [5:0] CONFIGOPTS = 6'h18;
  localparam bit [5:0] COMMAND    = 6'h20;
  localparam bit [5:0] RXDATA     = 6'h24;
  localparam bit [5:0] TXDATA     = 6'h28;

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;

  logic [5:0]  addr;
  logic        req, wr;
  logic [3:0]  be;
  logic [31:0] wdata, rdata;
  logic        sck, csb;
  wire  [3:0]  sd;

  spi_host_ot #(.NumCS(1)) dut (
    .clk_i(clk), .rst_ni(rst_n),
    .addr_i(addr), .req_i(req), .wr_i(wr), .be_i(be), .wdata_i(wdata), .rdata_o(rdata),
    .sck(sck), .csb(csb), .sd(sd)
  );

  //--------------------------------------------------------------------------
  // The dumb SPI device, now on the SHARED TRI-STATE BUS. It owns lane 1 only —
  // the host owns lane 0 at the same instant.
  //--------------------------------------------------------------------------
  logic [7:0] dev_shift_tx, dev_rx;
  int         dev_bits;
  logic       dev_miso, dev_oe;

  assign sd[1] = dev_oe ? dev_miso : 1'bz;   // lane 1 ONLY. Lanes 0/2/3 are not ours.

  initial begin
    dev_oe   = 1'b0;
    dev_miso = 1'b1;
    dev_bits = 0;
    dev_rx   = '0;
    @(negedge csb);
    dev_shift_tx = DEV_TX;
    dev_miso     = DEV_TX[7];   // bit 7 out BEFORE any sck edge exists
    dev_oe       = 1'b1;
    forever begin
      @(posedge sck);
      dev_rx   = {dev_rx[6:0], sd[0]};   // sample MOSI off the shared wire
      dev_bits = dev_bits + 1;
      @(negedge sck);
      dev_shift_tx = {dev_shift_tx[6:0], 1'b0};
      dev_miso     = dev_shift_tx[7];
    end
  end

  int sck_edges = 0;
  always @(posedge sck) sck_edges++;

  //--------------------------------------------------------------------------
  int errors = 0;
  logic [31:0] rx_word;

  task automatic chk(input bit ok, input string what);
    if (ok) $display("  PASS  %s", what);
    else begin
      $display("  FAIL  %s", what);
      errors++;
    end
  endtask

  task automatic reg_write(input bit [5:0] a, input bit [31:0] d, input bit [3:0] b = 4'hf);
    @(posedge clk);
    addr <= a; wdata <= d; be <= b; wr <= 1'b1; req <= 1'b1;
    @(posedge clk);
    req <= 1'b0; wr <= 1'b0;
  endtask

  task automatic reg_read(input bit [5:0] a, output bit [31:0] d);
    @(posedge clk);
    addr <= a; wr <= 1'b0; req <= 1'b1;
    @(posedge clk);
    req <= 1'b0;
    @(posedge clk);      // rdata is REGISTERED: request at N, data at N+1
    d = rdata;
  endtask

  initial begin
    req = 1'b0; wr = 1'b0; addr = '0; wdata = '0; be = '0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (4) @(posedge clk);

    // 1. CONTROL: SPIEN | OUTPUT_EN. Forget OUTPUT_EN and the DUT drives NOTHING.
    reg_write(CONTROL, (32'h1 << 31) | (32'h1 << 29) | 32'h7f);

    // 2. CONFIGOPTS: mode 0, clkdiv, csn lead/trail/idle = 2
    reg_write(CONFIGOPTS, (32'd2 << 24) | (32'd2 << 20) | (32'd2 << 16) | 32'(CLKDIV));

    // 3. TXDATA: push one byte (byte-enable selects it)
    reg_write(TXDATA, {24'h0, HOST_TX}, 4'b0001);

    // 4. COMMAND: len=0 (one byte), Standard, Bidir. The command launches on THIS WRITE.
    reg_write(COMMAND, (32'd3 << 23) | (32'd0 << 21) | (32'd0 << 20) | 32'd0);

    // 5. poll STATUS until the transfer has drained, then pop RXDATA
    begin
      int unsigned guard = 0;
      logic [31:0] st;
      do begin
        reg_read(STATUS, st);
        guard++;
      end while (st[24] && guard < 500);   // RXEMPTY
      chk(guard < 500, "RXDATA became non-empty (the transfer completed)");
    end
    reg_read(RXDATA, rx_word);

    repeat (20) @(posedge clk);

    $display("\n=== SLICE 0b: one SPI byte through the REGISTER BUS + tri-state pads ===");
    chk(sck_edges >= 8, $sformatf("sck toggled (%0d rising edges)", sck_edges));
    chk(dev_bits >= 8,  $sformatf("the device saw 8 sck edges (%0d)", dev_bits));
    chk(dev_rx == HOST_TX,
        $sformatf("the device received the host's byte: got %02h, expect %02h",
                  dev_rx, HOST_TX));
    chk(rx_word[7:0] == DEV_TX,
        $sformatf("the host received the device's byte: got %02h, expect %02h",
                  rx_word[7:0], DEV_TX));

    if (errors == 0) $display("\n*** SLICE 0b PASSED ***\n");
    else             $display("\n*** SLICE 0b FAILED (%0d) ***\n", errors);
    $finish;
  end

endmodule
