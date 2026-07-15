`include "uvm_macros.svh"
module tb_b;
  import uvm_pkg::*;
  import io_pkg::*;                       // consume the VIP BY REFERENCE (no local copy)
  logic clk = 0; always #5 clk = ~clk;
  io_if vif(clk);
  class b_test extends uvm_test;
    `uvm_component_utils(b_test)
    io_agent ag; io_cfg cfg;
    function new(string n, uvm_component p); super.new(n,p); endfunction
    function void build_phase(uvm_phase phase);
      cfg = io_cfg::type_id::create("cfg");
      cfg.vif = vif; cfg.is_active = UVM_PASSIVE;
      uvm_config_db#(io_cfg)::set(this, "ag", "cfg", cfg);
      ag = io_agent::type_id::create("ag", this);   // io_agent comes from the shared io_pkg
    endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      `uvm_info("BENCH_b", $sformatf("consuming shared VIP, io_pkg::QVIP_TAG=%s", io_pkg::QVIP_TAG), UVM_LOW)
      #100; phase.drop_objection(this);
    endtask
  endclass
  initial run_test("b_test");
endmodule
