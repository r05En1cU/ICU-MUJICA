`timescale 1ns/1ps
module tb;
  reg clk;
  reg rst_n;
  reg wr_en;
  reg rd_en;
  reg [7:0] din;
  wire [7:0] dout;
  wire full;
  wire empty;
  wire [2:0] count;

  sync_fifo_4x8 dut(.clk(clk), .rst_n(rst_n), .wr_en(wr_en), .rd_en(rd_en), .din(din), .dout(dout), .full(full), .empty(empty), .count(count));

  initial clk = 0;
  always #5 clk = ~clk;

  task check_flags;
    input [2:0] exp_count;
    input exp_empty;
    input exp_full;
    begin
      #1;
      if (count !== exp_count || empty !== exp_empty || full !== exp_full) begin
        $display("FAIL flags t=%0t count=%0d/%0d empty=%b/%b full=%b/%b", $time, count, exp_count, empty, exp_empty, full, exp_full);
        $finish;
      end
    end
  endtask

  task check_dout;
    input [7:0] exp;
    begin
      #1;
      if (dout !== exp) begin
        $display("FAIL dout t=%0t dout=%h/%h", $time, dout, exp);
        $finish;
      end
    end
  endtask

  initial begin
    rst_n = 0; wr_en = 0; rd_en = 0; din = 8'h00;
    #2; check_flags(3'd0, 1'b1, 1'b0);
    @(negedge clk); rst_n = 1;

    din = 8'h11; wr_en = 1; rd_en = 0; @(posedge clk); check_flags(3'd1, 1'b0, 1'b0);
    din = 8'h22; @(posedge clk); check_flags(3'd2, 1'b0, 1'b0);
    din = 8'h33; @(posedge clk); check_flags(3'd3, 1'b0, 1'b0);
    din = 8'h44; @(posedge clk); check_flags(3'd4, 1'b0, 1'b1);

    // Overflow attempt should keep count full.
    din = 8'h55; @(posedge clk); check_flags(3'd4, 1'b0, 1'b1);

    wr_en = 0; rd_en = 1; @(posedge clk); check_flags(3'd3, 1'b0, 1'b0); check_dout(8'h11);
    @(posedge clk); check_flags(3'd2, 1'b0, 1'b0); check_dout(8'h22);

    // Simultaneous read/write keeps count unchanged and preserves ordering.
    wr_en = 1; rd_en = 1; din = 8'h66; @(posedge clk); check_flags(3'd2, 1'b0, 1'b0); check_dout(8'h33);
    wr_en = 0; rd_en = 1; @(posedge clk); check_flags(3'd1, 1'b0, 1'b0); check_dout(8'h44);
    @(posedge clk); check_flags(3'd0, 1'b1, 1'b0); check_dout(8'h66);

    // Underflow attempt should keep empty.
    @(posedge clk); check_flags(3'd0, 1'b1, 1'b0);
    $display("PASS C03 sync_fifo_4x8 smoke");
    $finish;
  end
endmodule
