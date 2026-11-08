derive_pll_clocks
derive_clock_uncertainty

# core specific constraints

# Core (outclk_0, 16 MHz) and terminal video (outclk_1, 25 MHz) are
# asynchronous; term_display.sv's text RAM is a dual-clock RAM and the
# cursor/scroll position it reads across is only shown, never acted on.
set_clock_groups -asynchronous \
   -group [get_clocks {emu|pll|pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk}] \
   -group [get_clocks {emu|pll|pll_inst|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}]
