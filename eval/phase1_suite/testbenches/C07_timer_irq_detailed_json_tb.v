`timescale 1ns/1ps
module tb;
  reg clk;
  reg rst_n;
  reg enable;
  reg clear_irq;
  reg [15:0] period;
  wire irq;
  wire [15:0] count;

  timer_irq dut(.clk(clk), .rst_n(rst_n), .enable(enable), .clear_irq(clear_irq), .period(period), .irq(irq), .count(count));

  initial clk = 0;
  always #5 clk = ~clk;

  task check;
    input [15:0] exp_count;
    input exp_irq;
    begin
      #1;
      if (count !== exp_count || irq !== exp_irq) begin
        $display("FAIL t=%0t count=%0d/%0d irq=%b/%b", $time, count, exp_count, irq, exp_irq);
        $finish;
      end
    end
  endtask

  initial begin
    rst_n=0; enable=0; clear_irq=0; period=16'd3;
    #2; check(16'd0, 1'b0);
    @(negedge clk); rst_n=1;

    enable=1; @(posedge clk); check(16'd1, 1'b0);
    @(posedge clk); check(16'd2, 1'b0);
    @(posedge clk); check(16'd0, 1'b1);
    clear_irq=1; @(posedge clk); check(16'd1, 1'b0);
    clear_irq=0; enable=0; @(posedge clk); check(16'd1, 1'b0);
    period=16'd0; enable=1; @(posedge clk); check(16'd0, 1'b0);
    $display("PASS C07 timer_irq smoke");
    $finish;
  end
endmodule
