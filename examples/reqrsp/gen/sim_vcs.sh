#!/bin/sh
# Synopsys VCS runner -- reqrsp. Two-step (compile -> ./simv):
#   sh sim_vcs.sh +UVM_TESTNAME=<test>
# `-ntb_opts uvm` MUST be on the command line -- VCS rejects it inside a -f file.
vcs \
  -sverilog \
  -full64 \
  -ntb_opts uvm \
  -timescale=1ns/1ns \
  -debug_access+all \
  -top tb_top \
  -f compile.f || exit $?
exec ./simv "$@"
