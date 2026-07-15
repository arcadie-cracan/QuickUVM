=== paste into sha512_predictor.svh, class_item_additional seam ===
  // pragma quickuvm custom class_item_additional begin
  // The golden model: read a NIST CAVP .rsp vector, exactly as Caliptra's UVMF
  // SHA512_predictor does — $fopen/$fgets/$sscanf, no $system, no python, no DPI.
  // This is the whole point of the K0 win: plain SV file I/O drops straight into the
  // seam (T1's HMAC needed a C library over DPI; this does not).
  int    fd_r;
  string line_read, tmp1, tmp2;
  bit [511:0] expected;

  function string rsp_file(op_e op);
    case (op)
      sha224_op: return "SHA224ShortMsg.rsp";
      sha256_op: return "SHA256ShortMsg.rsp";
      sha384_op: return "SHA384ShortMsg.rsp";
      default:   return "SHA512ShortMsg.rsp";
    endcase
  endfunction

  function int result_shift(op_e op);  // left-align in 512 bits
    case (op)
      sha224_op: return 288;
      sha256_op: return 256;
      sha384_op: return 128;
      default:   return 0;
    endcase
  endfunction
  // pragma quickuvm custom class_item_additional end

=== paste into sha512_reference_model.svh, prediction_logic seam ===
  // pragma quickuvm custom prediction_logic begin
  // Ported from Caliptra's UVMF SHA512_predictor.svh (NIST .rsp lookup). Selects the
  // file by `op`, skips to the test_case_sel'th vector, parses the expected digest, and
  // left-aligns it in the 512-bit result. Same shape, no DPI.
  begin
    int line_skip = int'(t.test_case_sel) * 4 + 10;
    int cnt = 0;
    fd_r = $fopen(rsp_file(t.op), "r");
    if (fd_r) begin
      while (cnt < line_skip && !$feof(fd_r)) begin
        cnt++;
        void'($fgets(line_read, fd_r));
      end
      void'($sscanf(line_read, "%s %s %h", tmp1, tmp2, expected));
      $fclose(fd_r);
    end
    extr.result = expected << result_shift(t.op);
  end
  // pragma quickuvm custom prediction_logic end
