`timescale 1ns/1ps
module tb;
  reg [7:0] req;
  wire valid;
  wire [2:0] index;
  wire [7:0] grant;

  priority_encoder8 dut(.req(req), .valid(valid), .index(index), .grant(grant));

  task check;
    input [7:0] r;
    input exp_valid;
    input [2:0] exp_index;
    input [7:0] exp_grant;
    begin
      req = r;
      #1;
      if (valid !== exp_valid || index !== exp_index || grant !== exp_grant) begin
        $display("FAIL req=%b valid=%b/%b index=%0d/%0d grant=%b/%b", req, valid, exp_valid, index, exp_index, grant, exp_grant);
        $finish;
      end
    end
  endtask

  initial begin
    check(8'b00000000, 1'b0, 3'd0, 8'b00000000);
    check(8'b00000001, 1'b1, 3'd0, 8'b00000001);
    check(8'b00000010, 1'b1, 3'd1, 8'b00000010);
    check(8'b10000000, 1'b1, 3'd7, 8'b10000000);
    check(8'b11111111, 1'b1, 3'd0, 8'b00000001);
    check(8'b10101000, 1'b1, 3'd3, 8'b00001000);
    $display("PASS C01 priority_encoder8 smoke");
    $finish;
  end
endmodule
