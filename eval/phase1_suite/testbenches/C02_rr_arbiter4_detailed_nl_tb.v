`timescale 1ns/1ps
module tb;
  reg clk;
  reg rst_n;
  reg enable;
  reg [3:0] req;
  wire [3:0] grant;
  wire grant_valid;
  wire [1:0] grant_idx;
  wire [1:0] last_grant_dbg;

  rr_arbiter4 dut(
    .clk(clk), .rst_n(rst_n), .enable(enable), .req(req),
    .grant(grant), .grant_valid(grant_valid), .grant_idx(grant_idx), .last_grant_dbg(last_grant_dbg)
  );

  initial clk = 0;
  always #5 clk = ~clk;

  task check;
    input [3:0] exp_grant;
    input exp_valid;
    input [1:0] exp_idx;
    input [1:0] exp_last;
    begin
      #1;
      if (grant !== exp_grant || grant_valid !== exp_valid || grant_idx !== exp_idx || last_grant_dbg !== exp_last) begin
        $display("FAIL t=%0t req=%b enable=%b grant=%b/%b valid=%b/%b idx=%0d/%0d last=%0d/%0d",
          $time, req, enable, grant, exp_grant, grant_valid, exp_valid, grant_idx, exp_idx, last_grant_dbg, exp_last);
        $finish;
      end
    end
  endtask

  initial begin
    rst_n = 0; enable = 0; req = 4'b0000;
    #2; check(4'b0000, 1'b0, 2'd0, 2'd3);
    @(negedge clk); rst_n = 1;

    enable = 1; req = 4'b1111; @(posedge clk); check(4'b0001, 1'b1, 2'd0, 2'd0);
    @(posedge clk); check(4'b0010, 1'b1, 2'd1, 2'd1);
    @(posedge clk); check(4'b0100, 1'b1, 2'd2, 2'd2);
    @(posedge clk); check(4'b1000, 1'b1, 2'd3, 2'd3);
    @(posedge clk); check(4'b0001, 1'b1, 2'd0, 2'd0);

    enable = 0; req = 4'b1111; @(posedge clk); check(4'b0000, 1'b0, 2'd0, 2'd0);
    enable = 1; req = 4'b0000; @(posedge clk); check(4'b0000, 1'b0, 2'd0, 2'd0);
    req = 4'b0001; @(posedge clk); check(4'b0001, 1'b1, 2'd0, 2'd0);
    req = 4'b0101; @(posedge clk); check(4'b0100, 1'b1, 2'd2, 2'd2);
    req = 4'b0101; @(posedge clk); check(4'b0001, 1'b1, 2'd0, 2'd0);

    #2 rst_n = 0; #1; check(4'b0000, 1'b0, 2'd0, 2'd3);
    $display("PASS C02 rr_arbiter4 smoke");
    $finish;
  end
endmodule
