//----------------------------------------------------------------------
// es_adaptp — a minimal Adaptive-Proportion health test, modelled on OpenTitan
// entropy_src (entropy_src_adaptp_ht.sv + the ALERT_SUMMARY_FAIL_COUNTS path).
//
// THE QUESTION THIS BENCH EXISTS TO ANSWER (docs/es_adaptp_assessment.md):
//   entropy_src's health tests are WINDOWED statistics: N raw samples accumulate,
//   and ONE pass/fail verdict emerges per window (not per sample). Can QuickUVM's
//   predictor seam — `predict(item) -> item`, structurally one-in-one-out — express
//   an N:1 windowed statistic? And can it hold the SECOND, cross-window level:
//   consecutive failing windows accumulate and, at a threshold, latch an alert
//   (a passing window resets the run — OpenTitan's ALERT_SUMMARY_FAIL_COUNTS).
//
// The statistic (ADAPTP, threshold_scope = summed): over WINDOW symbols, count the
// 1-bits across the RngBusWidth-wide symbol; fail if the count is > HI or < LO
// (strict, matching the RTL). This is a FAITHFUL shrink of the real block: real
// FIPS window = 512 symbols (2048 bits); here WINDOW is small so a sim completes.
// Thresholds are parameters here; the real block programs them via CSR (ADAPTP_HI/
// LO_THRESHOLD) — an orthogonal, already-expressible RAL concern, held out to keep
// the windowing question clean.
//----------------------------------------------------------------------
module es_adaptp #(
  parameter int SYMW         = 4,   // RngBusWidth: bits per entropy symbol
  parameter int WINDOW       = 8,   // samples per health-test window (real FIPS: 512)
  parameter int LO           = 8,   // ADAPTP_LO_THRESHOLD (min 1-bits over the window)
  parameter int HI           = 24,  // ADAPTP_HI_THRESHOLD (max 1-bits over the window)
  parameter int ALERT_THRESH = 2    // consecutive failing windows that latch an alert
) (
  input  logic            clk,
  input  logic            rst_n,
  input  logic [SYMW-1:0] sample,       // one entropy symbol
  input  logic            valid,        // sample is live this cycle
  output logic            window_done,  // pulses on the cycle a window completes
  output logic [15:0]     ones_cnt,     // 1-bits in the completed window (valid @window_done)
  output logic            test_fail,    // this window failed ADAPTP     (valid @window_done)
  output logic            alert         // consecutive-fail run reached ALERT_THRESH (latched)
);
  localparam int CW = $clog2(WINDOW + 1);

  logic [CW-1:0] scount;    // valid samples seen so far in this window
  logic [15:0]   osum;      // running 1-bit count for this window
  logic [15:0]   fail_run;  // consecutive failing windows (reset by a passing window)
  logic          alert_q;   // latched alert

  // popcount of one symbol
  function automatic logic [SYMW:0] popc(input logic [SYMW-1:0] s);
    popc = '0;
    for (int i = 0; i < SYMW; i++) popc += s[i];
  endfunction

  // This valid sample completes the window.
  wire        last     = valid && (scount == CW'(WINDOW - 1));
  // The window's full 1-bit count, INCLUDING this sample (combinational @boundary).
  wire [15:0] osum_now = osum + (valid ? 16'(popc(sample)) : 16'd0);
  wire        fail_now = last && ((osum_now > 16'(HI)) || (osum_now < 16'(LO)));
  // Alert latches the cycle the run crosses the threshold (combinational so it aligns
  // with test_fail, then held by alert_q).
  wire        alert_set = fail_now && ((fail_run + 16'd1) >= 16'(ALERT_THRESH));

  assign window_done = last;
  assign ones_cnt    = osum_now;
  assign test_fail   = fail_now;
  assign alert       = alert_q || alert_set;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      scount <= '0; osum <= '0; fail_run <= '0; alert_q <= 1'b0;
    end else if (valid) begin
      if (last) begin
        scount <= '0;
        osum   <= '0;
        if (fail_now) fail_run <= fail_run + 16'd1;  // another failing window
        else          fail_run <= '0;                // a passing window resets the run
        if (alert_set) alert_q <= 1'b1;              // latch, stays until reset
      end else begin
        scount <= scount + 1'b1;
        osum   <= osum_now;
      end
    end
  end
endmodule
