# Worst setup paths of the compiled design (quartus_sta -t sta_paths.tcl):
#   output_files/worst_paths.txt        60 worst paths, all clocks
#   output_files/worst_paths_core.txt   30 worst into the core clock (16 MHz)
#   output_files/worst_paths_video.txt  30 worst into the video clock (25 MHz)
#   output_files/worst_paths_full.txt   the 5 worst into the core clock, in detail
project_open Synclavier
create_timing_netlist
read_sdc
update_timing_netlist
set core  [get_clocks {emu|pll|pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk}]
set video [get_clocks {emu|pll|pll_inst|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}]
report_timing -setup -npaths 60 -detail summary -file output_files/worst_paths.txt
report_timing -setup -npaths 30 -detail summary -to_clock $core -file output_files/worst_paths_core.txt
report_timing -setup -npaths 30 -detail summary -to_clock $video -file output_files/worst_paths_video.txt
report_timing -setup -npaths 5 -detail full_path -to_clock $core -file output_files/worst_paths_full.txt
delete_timing_netlist
project_close
