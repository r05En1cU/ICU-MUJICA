`timescale 1ns/1ps
module tb;
  reg clk;
  reg rst_n;
  reg [3:0] din;
  wire [3:0] dout;
  wire valid;
  wire [1:0] stage;

  reg [3:0] mux_a, mux_b, mux_c, mux_d;
  reg [1:0] mux_sel;
  wire [3:0] mux_y;

  reg edge_in;
  wire edge_out;

  reg fifo_wr_en;
  reg fifo_rd_en;
  reg [3:0] fifo_din;
  wire fifo_full;
  wire fifo_empty;
  wire [3:0] fifo_dout;
  wire [1:0] fifo_count;

  integer i;
  integer seen_valid;

  staged_mux_fifo_top dut(
    .clk(clk), .rst_n(rst_n), .din(din),
    .dout(dout), .valid(valid), .stage(stage)
  );

  mux_4to1 u_mux_check(
    .a(mux_a), .b(mux_b), .c(mux_c), .d(mux_d),
    .sel(mux_sel), .y(mux_y)
  );

  rising_edge_detector u_edge_check(
    .clk(clk), .rst_n(rst_n), .in(edge_in), .out(edge_out)
  );

  sync_fifo_2x4 u_fifo_check(
    .clk(clk), .rst_n(rst_n), .wr_en(fifo_wr_en), .rd_en(fifo_rd_en),
    .din(fifo_din), .full(fifo_full), .empty(fifo_empty),
    .dout(fifo_dout), .count(fifo_count)
  );

  initial clk = 0;
  always #5 clk = ~clk;

  task fail;
    input [1023:0] msg;
    begin
      $display("FAIL %0s", msg);
      $finish;
    end
  endtask

  task tick;
    begin
      @(posedge clk); #1;
    end
  endtask

  task expect1;
    input actual;
    input expected;
    input [1023:0] msg;
    begin
      if (actual !== expected) begin
        $display("FAIL %0s actual=%b expected=%b", msg, actual, expected);
        $finish;
      end
    end
  endtask

  task expect2;
    input [1:0] actual;
    input [1:0] expected;
    input [1023:0] msg;
    begin
      if (actual !== expected) begin
        $display("FAIL %0s actual=%b expected=%b", msg, actual, expected);
        $finish;
      end
    end
  endtask

  task expect4;
    input [3:0] actual;
    input [3:0] expected;
    input [1023:0] msg;
    begin
      if (actual !== expected) begin
        $display("FAIL %0s actual=%h expected=%h", msg, actual, expected);
        $finish;
      end
    end
  endtask

  task run_mux_checks;
    begin
      mux_a = 4'h0; mux_b = 4'h1; mux_c = 4'hA; mux_d = 4'h5;
      mux_sel = 2'd0; #1; expect4(mux_y, 4'h0, "mux sel0 selects a");
      mux_sel = 2'd1; #1; expect4(mux_y, 4'h1, "mux sel1 selects b");
      mux_sel = 2'd2; #1; expect4(mux_y, 4'hA, "mux sel2 selects c");
      mux_sel = 2'd3; #1; expect4(mux_y, 4'h5, "mux sel3 selects d");
    end
  endtask

  task run_edge_checks;
    begin
      edge_in = 1'b0;
      rst_n = 1'b0;
      repeat (2) tick;
      expect1(edge_out, 1'b0, "edge reset clears out");
      @(negedge clk); rst_n = 1'b1;
      tick;
      expect1(edge_out, 1'b0, "edge idle low");
      edge_in = 1'b1;
      tick;
      expect1(edge_out, 1'b1, "edge rising pulse asserted");
      tick;
      expect1(edge_out, 1'b0, "edge pulse is one cycle");
      edge_in = 1'b0;
      tick;
      expect1(edge_out, 1'b0, "edge falling does not pulse");
      edge_in = 1'b1;
      tick;
      expect1(edge_out, 1'b1, "edge second rising pulse asserted");
      tick;
      expect1(edge_out, 1'b0, "edge second pulse is one cycle");
    end
  endtask

  task run_fifo_checks;
    begin
      fifo_wr_en = 1'b0;
      fifo_rd_en = 1'b0;
      fifo_din = 4'h0;
      rst_n = 1'b0;
      repeat (2) tick;
      expect2(fifo_count, 2'd0, "fifo reset count");
      expect1(fifo_empty, 1'b1, "fifo reset empty");
      expect1(fifo_full, 1'b0, "fifo reset not full");
      expect4(fifo_dout, 4'h0, "fifo reset dout");

      @(negedge clk); rst_n = 1'b1;
      fifo_wr_en = 1'b1; fifo_rd_en = 1'b0; fifo_din = 4'h1;
      tick;
      expect2(fifo_count, 2'd1, "fifo one write count");
      expect1(fifo_empty, 1'b0, "fifo one write not empty");
      expect1(fifo_full, 1'b0, "fifo one write not full");

      fifo_din = 4'h2;
      tick;
      expect2(fifo_count, 2'd2, "fifo second write count");
      expect1(fifo_full, 1'b1, "fifo full after two writes");
      expect1(fifo_empty, 1'b0, "fifo full not empty");

      fifo_din = 4'h3;
      tick;
      expect2(fifo_count, 2'd2, "fifo ignores write while full");
      expect1(fifo_full, 1'b1, "fifo remains full after ignored write");

      fifo_wr_en = 1'b0; fifo_rd_en = 1'b1;
      tick;
      expect4(fifo_dout, 4'h1, "fifo first read data");
      expect2(fifo_count, 2'd1, "fifo first read count");
      expect1(fifo_full, 1'b0, "fifo first read not full");
      expect1(fifo_empty, 1'b0, "fifo first read not empty");

      tick;
      expect4(fifo_dout, 4'h2, "fifo second read data");
      expect2(fifo_count, 2'd0, "fifo second read count");
      expect1(fifo_empty, 1'b1, "fifo empty after two reads");

      tick;
      expect2(fifo_count, 2'd0, "fifo ignores read while empty");
      expect1(fifo_empty, 1'b1, "fifo remains empty after ignored read");

      fifo_rd_en = 1'b0; fifo_wr_en = 1'b1; fifo_din = 4'hA;
      tick;
      expect2(fifo_count, 2'd1, "fifo write A count");

      fifo_rd_en = 1'b1; fifo_wr_en = 1'b1; fifo_din = 4'hB;
      tick;
      expect4(fifo_dout, 4'hA, "fifo simultaneous read/write reads old item");
      expect2(fifo_count, 2'd1, "fifo simultaneous read/write count unchanged");

      fifo_wr_en = 1'b0; fifo_rd_en = 1'b1;
      tick;
      expect4(fifo_dout, 4'hB, "fifo read item written during simultaneous op");
      expect2(fifo_count, 2'd0, "fifo final empty count");
    end
  endtask

  task run_top_checks;
    begin
      din = 4'h0;
      rst_n = 1'b0;
      repeat (2) tick;
      expect2(stage, 2'd0, "top reset stage");
      expect1(valid, 1'b0, "top reset valid");
      expect4(dout, 4'h0, "top reset dout");

      @(negedge clk); rst_n = 1'b1;
      din = 4'hF;
      tick; expect2(stage, 2'd1, "top stage step 1");
      tick; expect2(stage, 2'd2, "top stage step 2");
      tick; expect2(stage, 2'd3, "top stage step 3");
      tick; expect2(stage, 2'd0, "top stage wraps to 0");
      tick; expect2(stage, 2'd1, "top stage continues after wrap");

      seen_valid = 0;
      for (i = 0; i < 32; i = i + 1) begin
        din = i[3:0];
        tick;
        if (^dout === 1'bx) fail("top dout contains X after reset release");
        if (valid !== 1'b0 && valid !== 1'b1) fail("top valid contains X/Z after reset release");
        if (valid === 1'b1) seen_valid = 1;
      end
      if (seen_valid == 0) fail("top valid never asserted during FIFO activity window");
    end
  endtask

  initial begin
    $display("=== Cextra strict hierarchical spec/generation test start ===");
    din = 4'h0;
    mux_a = 4'h0; mux_b = 4'h0; mux_c = 4'h0; mux_d = 4'h0; mux_sel = 2'd0;
    edge_in = 1'b0;
    fifo_wr_en = 1'b0; fifo_rd_en = 1'b0; fifo_din = 4'h0;
    rst_n = 1'b0;

    run_mux_checks;
    run_edge_checks;
    run_fifo_checks;
    run_top_checks;

    $display("PASS Cextra strict hierarchical spec/generation test");
    $finish;
  end
endmodule
