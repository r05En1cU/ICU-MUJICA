`timescale 1ns/1ps
module tb;
  reg clk;
  reg rst_n;
  reg start;
  reg [7:0] data;
  reg baud_tick;
  wire tx;
  wire busy;
  wire done;

  uart_tx_lite dut(.clk(clk), .rst_n(rst_n), .start(start), .data(data), .baud_tick(baud_tick), .tx(tx), .busy(busy), .done(done));

  initial clk = 0;
  always #5 clk = ~clk;

  task tick;
    begin
      baud_tick = 1'b1;
      @(posedge clk);
      #1;
      baud_tick = 1'b0;
    end
  endtask

  task expect;
    input exp_tx;
    input exp_busy;
    input exp_done;
    begin
      #1;
      if (tx !== exp_tx || busy !== exp_busy || done !== exp_done) begin
        $display("FAIL t=%0t tx=%b/%b busy=%b/%b done=%b/%b", $time, tx, exp_tx, busy, exp_busy, done, exp_done);
        $finish;
      end
    end
  endtask

  initial begin
    rst_n=0; start=0; data=8'hA5; baud_tick=0;
    #2; expect(1'b1, 1'b0, 1'b0);
    @(negedge clk); rst_n=1;
    #1; expect(1'b1, 1'b0, 1'b0);

    start=1; @(posedge clk); #1; start=0; expect(1'b0, 1'b1, 1'b0); // start bit may appear immediately after accepting start
    tick(); expect(1'b1, 1'b1, 1'b0); // data bit 0 of 8'hA5 is 1
    tick(); expect(1'b0, 1'b1, 1'b0); // bit 1
    tick(); expect(1'b1, 1'b1, 1'b0); // bit 2
    tick(); expect(1'b0, 1'b1, 1'b0); // bit 3
    tick(); expect(1'b0, 1'b1, 1'b0); // bit 4
    tick(); expect(1'b1, 1'b1, 1'b0); // bit 5
    tick(); expect(1'b0, 1'b1, 1'b0); // bit 6
    tick(); expect(1'b1, 1'b1, 1'b0); // bit 7
    tick(); expect(1'b1, 1'b1, 1'b0); // stop bit
    tick(); expect(1'b1, 1'b0, 1'b1); // done pulse after stop
    @(posedge clk); #1; expect(1'b1, 1'b0, 1'b0);
    $display("PASS C08 uart_tx_lite smoke");
    $finish;
  end
endmodule
