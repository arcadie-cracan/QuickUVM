// Paste into gen/rd_responder_seq.svh. The OoO engine a scoping pass claimed makes
// multi-outstanding OoO "expressible" — it holds a per-ID queue and reorders. Run it and
// watch the STRAND: `outstanding` builds to 2, but only ONE response is driven per get(),
// and the loop then blocks forever on a new request. The tail of the burst is never answered.

// --- class_item_additional ---
  rd_item id_q[16][$];                         // per-ID outstanding queues
  int     outstanding;
  function int pick_ready_id();                // random non-empty ID (cross-ID reorder)
    int c[$]; foreach (id_q[i]) if (id_q[i].size()) c.push_back(i);
    return c.size() ? c[$urandom_range(0, c.size()-1)] : -1;
  endfunction

// --- response_logic (between the GENERATED get() and start_item/finish_item) ---
  id_q[req.arid].push_back(req); outstanding++;
  #100ns;                                      // hold, so the rest of the burst buffers
  begin rd_item e; while (p_sequencer.request_fifo.try_get(e)) begin
    id_q[e.arid].push_back(e); outstanding++; end end
  begin
    int pid = pick_ready_id();
    rd_item chosen = id_q[pid].pop_front(); outstanding--;
    rsp.copy(chosen); rsp.rid = chosen.arid; rsp.rvalid = 1'b1; rsp.rlast = 1'b1;
  end
  $display("[RESP %0t] DRIVE one rsp rid=%0d, but outstanding=%0d STILL QUEUED",
           $time, rsp.rid, outstanding);
