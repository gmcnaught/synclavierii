# Worst setup paths of the compiled design (quartus_sta -t sta_paths.tcl),
# written to output_files/worst_paths.txt (summary, 60 paths) and
# output_files/worst_paths_full.txt (the 5 worst in detail).
project_open Synclavier
create_timing_netlist
read_sdc
update_timing_netlist
report_timing -setup -npaths 60 -detail summary -file output_files/worst_paths.txt
report_timing -setup -npaths 5 -detail full_path -file output_files/worst_paths_full.txt
delete_timing_netlist
project_close
