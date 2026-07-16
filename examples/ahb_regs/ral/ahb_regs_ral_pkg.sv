//----------------------------------------------------------------------
// ahb_regs_ral_pkg — the external uvm_reg_block for the ahb_regs slave (F2-style: the
// generator consumes this by NAME via register_model:, it does not emit it). Modelled on
// examples/regfile/ral/regfile_ral_pkg.sv. Four 32-bit RW registers at word offsets.
//----------------------------------------------------------------------
`ifndef AHB_REGS_RAL_PKG__SV
`define AHB_REGS_RAL_PKG__SV

`include "uvm_macros.svh"

package ahb_regs_ral_pkg;
  import uvm_pkg::*;

  class rw32_reg extends uvm_reg;
    rand uvm_reg_field f;
    protected string        hdl_slice;
    protected uvm_reg_data_t reset_val;

    `uvm_object_utils(rw32_reg)

    function new(string name = "rw32_reg");
      super.new(name, 32, UVM_NO_COVERAGE);
    endfunction

    function void set_slice(string s, uvm_reg_data_t rv);
      hdl_slice = s; reset_val = rv;
    endfunction

    virtual function void build();
      f = uvm_reg_field::type_id::create("f");
      // configure(parent, size, lsb, access, volatile, reset, has_reset, is_rand, indiv)
      f.configure(this, 32, 0, "RW", 0, reset_val, 1, 1, 1);
      if (hdl_slice != "")
        add_hdl_path_slice(hdl_slice, 0, 32, 1);   // full-register backdoor slice
    endfunction
  endclass

  class ahb_regs_reg_block extends uvm_reg_block;
    rand rw32_reg ctrl;
    rand rw32_reg cfg;
    rand rw32_reg scratch;
    rand rw32_reg status;

    `uvm_object_utils(ahb_regs_reg_block)

    function new(string name = "ahb_regs_reg_block");
      super.new(name, UVM_NO_COVERAGE);
    endfunction

    function rw32_reg new_reg(string name, uvm_reg_data_t reset_val,
                             string hdl_slice, int offset);
      rw32_reg r = rw32_reg::type_id::create(name);
      r.set_slice(hdl_slice, reset_val);
      r.configure(this);
      r.build();
      default_map.add_reg(r, offset, "RW");
      return r;
    endfunction

    // build() populates the model but does NOT lock it — the generated base test owns
    // create() -> build() -> lock_model().
    virtual function void build();
      default_map = create_map("default_map", 0, 4, UVM_LITTLE_ENDIAN);
      ctrl    = new_reg("ctrl",    32'h0000_0000, "regs[0]", 'h0);
      cfg     = new_reg("cfg",     32'h0000_00FF, "regs[1]", 'h4);
      scratch = new_reg("scratch", 32'hDEAD_BEEF, "regs[2]", 'h8);
      status  = new_reg("status",  32'hCAFE_0000, "regs[3]", 'hC);
    endfunction
  endclass

endpackage

`endif
