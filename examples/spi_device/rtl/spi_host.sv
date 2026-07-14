// An SPI HOST (mode 0). It GENERATES sck — so sck is a DUT OUTPUT, and the TB must only
// ever SAMPLE it (`clock: {source: dut}`). A clkgen on this net would fight the DUT's own
// driver and Xcelium rejects it (*E,MULDRN).
//
// Full-duplex: on every sck rising edge the host samples MISO while the device samples
// MOSI. So the device's MISO bit k CANNOT be a function of MOSI bit k — it has to already
// be on the wire. That is what `respond: prefetch` exists for.
module spi_host #(parameter int DIV = 2) (
  input  logic       clk,
  input  logic       rst_n,
  output logic       sck,
  output logic       csb,
  output logic       mosi,
  input  logic       miso,
  // observable: what the host RECEIVED from the device, and how many frames have completed
  output logic [7:0] rx_byte,
  output logic [7:0] frame_cnt
);
  typedef enum logic [1:0] {IDLE, GAP, XFER} state_e;
  state_e            state;
  logic [7:0]        sh_tx, sh_rx;
  logic [2:0]        bit_i;
  logic [7:0]        div_ctr;
  logic              half;   // 0 = about to rise, 1 = about to fall

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE; sck <= 1'b0; csb <= 1'b1; mosi <= 1'b0;
      sh_tx <= 8'h3C; sh_rx <= '0; bit_i <= '0; div_ctr <= '0; half <= 1'b0;
      rx_byte <= '0; frame_cnt <= '0;
    end else begin
      div_ctr <= div_ctr + 8'd1;
      if (div_ctr == DIV[7:0] - 8'd1) begin
        div_ctr <= '0;
        case (state)
          IDLE: begin                      // open the frame; present bit 7 before any edge
            csb   <= 1'b0;
            mosi  <= sh_tx[7];
            bit_i <= '0;
            half  <= 1'b0;
            sck   <= 1'b0;
            state <= XFER;
          end
          XFER: begin
            half <= ~half;
            if (!half) begin               // RISING edge: both ends sample
              sck   <= 1'b1;
              sh_rx <= {sh_rx[6:0], miso};
            end else begin                 // FALLING edge: shift out the next bit
              sck <= 1'b0;
              if (bit_i == 3'd7) begin
                csb       <= 1'b1;
                frame_cnt <= frame_cnt + 8'd1;
                sh_tx     <= sh_tx + 8'd1;
                state     <= GAP;
              end else begin
                bit_i <= bit_i + 3'd1;
                mosi  <= sh_tx[6 - bit_i];
              end
            end
          end
          GAP: state <= IDLE;              // a gap between frames
          default: state <= IDLE;
        endcase
      end
      // Latch the received byte on the 8th RISING edge — the same edge the device's last
      // MISO bit is sampled on. sh_rx holds bits 7..1; `miso` is bit 0, live on the wire.
      if (state == XFER && !half && bit_i == 3'd7 && div_ctr == DIV[7:0] - 8'd1)
        rx_byte <= {sh_rx[6:0], miso};
    end
  end
endmodule
