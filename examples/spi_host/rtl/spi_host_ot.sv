// OURS — a derivative of OpenTitan's `spi_host.sv` (Apache-2.0).
//
// Statement of changes (Apache-2.0 §4(b)):
//   * the TL-UL interface is replaced by `spi_host_reg_generic` (a generic register bus);
//   * `spi_host_window` (two TL-UL SRAM adapters for the TX/RX FIFO windows) is absorbed
//     into that same register block;
//   * alerts, RACL, and the `passthrough_i/o` ports are dropped (passthrough is typed
//     `spi_device_pkg::passthrough_req_t` and would pull in the entire spi_device IP);
//   * the SPI pins are exposed as a TRI-STATE bus (`sd` as an inout), which is what a real
//     pad ring does and what the testbench's device agent shares the wire with. OpenTitan's
//     top exposes the pre-pad `cio_sd_o` / `cio_sd_en_o` / `cio_sd_i` triplet instead.
//
// `spi_host_core` and everything under it are VENDORED UNMODIFIED. The module name is
// `spi_host_ot` (not `spi_host`) purely to avoid a collision with examples/spi_device's own
// hand-written host.
`timescale 1ns/1ns

module spi_host_ot
  import spi_host_cmd_pkg::*;
#(
  parameter int NumCS = 1
) (
  input  logic        clk_i,
  input  logic        rst_ni,

  // generic register bus (the declared normalisation)
  input  logic [5:0]  addr_i,
  input  logic        req_i,
  input  logic        wr_i,
  input  logic [3:0]  be_i,
  input  logic [31:0] wdata_i,
  output logic [31:0] rdata_o,

  // SPI — a real, shared, tri-state bus
  output logic        sck,
  output logic        csb,
  inout  wire  [3:0]  sd
);

  logic        en, sw_rst, output_en;
  command_t    command;
  logic        command_valid, command_ready;
  logic [31:0] tx_data;
  logic [3:0]  tx_be;
  logic        tx_valid, tx_ready, tx_byte_select_full;
  logic [31:0] rx_data;
  logic        rx_valid, rx_ready;
  logic             core_sck;
  logic [NumCS-1:0] core_csb;   // the core carries one csb per chip select
  logic [3:0]  core_sd_o, core_sd_en;
  logic [3:0]  core_sd_i;
  logic        rx_stall, tx_stall, active;

  spi_host_reg_generic u_reg (
    .clk_i, .rst_ni,
    .addr_i, .req_i, .wr_i, .be_i, .wdata_i, .rdata_o,
    .en_o(en), .sw_rst_o(sw_rst), .output_en_o(output_en),
    .command_o(command), .command_valid_o(command_valid), .command_ready_i(command_ready),
    .tx_data_o(tx_data), .tx_be_o(tx_be), .tx_valid_o(tx_valid), .tx_ready_i(tx_ready),
    .rx_data_i(rx_data), .rx_valid_i(rx_valid), .rx_ready_o(rx_ready),
    .rx_stall_i(rx_stall), .tx_stall_i(tx_stall), .active_i(active)
  );

  // VENDORED, UNMODIFIED.
  spi_host_core #(.NumCS(NumCS)) u_core (
    .clk_i, .rst_ni,
    .command_i(command), .command_csid_i(1'b0),
    .command_valid_i(command_valid), .command_ready_o(command_ready),
    .en_i(en),
    .tx_data_i(tx_data), .tx_be_i(tx_be), .tx_valid_i(tx_valid),
    .tx_ready_o(tx_ready), .tx_byte_select_full_o(tx_byte_select_full),
    .rx_data_o(rx_data), .rx_valid_o(rx_valid), .rx_ready_i(rx_ready),
    .sw_rst_i(sw_rst),
    .sck_o(core_sck), .csb_o(core_csb),
    .sd_o(core_sd_o), .sd_en_o(core_sd_en), .sd_i(core_sd_i),
    .rx_stall_o(rx_stall), .tx_stall_o(tx_stall), .active_o(active)
  );

  //--------------------------------------------------------------------------------
  // The pad ring. CONTROL.OUTPUT_EN gates EVERY output — sck, csb and all four sd lanes
  // (OpenTitan does this in spi_host.sv). It RESETS TO 0, so a DUT straight out of reset
  // drives nothing at all: with pull-ups the bus floats high and looks quiet and legal.
  // No X, no error, no protocol violation. A bench whose sequence forgets to set it runs
  // clean and tests nothing.
  //--------------------------------------------------------------------------------
  assign sck = output_en ? core_sck    : 1'b0;
  assign csb = output_en ? core_csb[0] : 1'b1;   // csb idles HIGH

  // PER-LANE tri-state. The host drives sd[0] (MOSI) while the DEVICE drives sd[1] (MISO)
  // AT THE SAME INSTANT — in standard mode `core_sd_en` is 4'b0001. A scalar enable cannot
  // express this, which is exactly why QuickUVM's `inouts` gained a per-lane one.
  for (genvar i = 0; i < 4; i++) begin : g_sd_pad
    assign sd[i] = (output_en && core_sd_en[i]) ? core_sd_o[i] : 1'bz;
  end
  assign core_sd_i = sd;

  // Weak pull-ups, as a real SPI board has. NB a `pullup` primitive is ILLEGAL inside an
  // interface, but legal in a module; a weak continuous assign is the portable equivalent
  // and loses to any real driver.
  assign (weak1, weak0) sd = 4'b1111;

endmodule
