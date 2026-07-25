#!/bin/sh
# Cadence Xcelium runner -- reqrsp. Run from this directory:
#   sh sim_xcelium.sh +UVM_TESTNAME=<test>
# xrun is a single call (compile + elaborate + simulate) and takes everything in
# the filelist, so this is a thin wrapper over the portable core `compile.f`.
exec xrun \
  -uvm \
  -access +rwc \
  -timescale 1ns/1ns \
  -top tb_top \
  -f compile.f \
  "$@"
