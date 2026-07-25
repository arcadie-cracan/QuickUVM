#!/bin/sh
# Siemens Questa runner (qrun, single call) -- reqrsp. Run:
#   sh sim_questa.sh +UVM_TESTNAME=<test>
# qrun auto-creates the work library, so no separate `vlib work` is needed.
exec qrun \
  -uvm \
  -timescale 1ns/1ns \
  -top tb_top \
  -f compile.f \
  "$@"
