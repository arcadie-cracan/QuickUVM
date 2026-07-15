#include <stdlib.h>
#include "svdpi.h"
// stand-in for the lowRISC Spike fork's cosim API
void* cosim_init(void)            { static int st; return &st; }
int   cosim_step(void* h, unsigned pc, unsigned insn, unsigned* rd) { *rd = pc ^ insn; return 0; }
