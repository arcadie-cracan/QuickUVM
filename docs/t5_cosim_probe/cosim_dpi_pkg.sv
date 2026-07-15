package cosim_dpi_pkg;
  import "DPI-C" function chandle cosim_init();
  import "DPI-C" function int cosim_step(chandle h, int unsigned pc, int unsigned insn, output int unsigned rd);
endpackage
