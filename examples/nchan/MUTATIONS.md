# nchan — mutation proof

Baseline: **3× TEST PASSED — 102 Ran / 102 Passed each, 0 errors** (one scoreboard per channel).

## Break one channel — only its scoreboard fails

Mutation (`rtl/nchan.sv`): channel 1 latches the wrong value —

    else if (v[i]) q[i] <= (i==1) ? ~d[i] : d[i];

Result: **only `ch_1`'s scoreboard fails**:

```
UVM_ERROR nchan_ch_1_comparator.svh(125): ch_1_sb.cmp [ERROR] Expected q=0, Actual q=1 ...
   (196 errors, ALL from nchan_ch_1_comparator; ch_0 and ch_2 stay PASSED)
```

This proves two things at once:

- **Per-channel independence** — the N replicas each have their own scoreboard checking their own
  slice, so corrupting one channel does not touch the others.
- **Correct index mapping** — corrupting channel **1** of the RTL fails **`ch_1`'s** scoreboard (not
  ch_0 or ch_2), so the vectored-DUT concatenation `{ch_2, ch_1, ch_0}` really does map replica *i*
  to bit *i* of each port. A binding that reversed or shuffled the slices would have failed the
  wrong scoreboard.
