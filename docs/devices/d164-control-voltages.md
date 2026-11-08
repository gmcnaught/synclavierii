# D164/D165: control-voltage outputs (keyboard filter/trigger board)

Option `o#d164` ("D164 (kbd filter/trigger bd)", SYSLITS). Write-only DAC
select and value.

| Device | Write |
|---|---|
| D164 | DAC select: 0 LP filter CV, 1 HP filter CV, 2 BP filter CV, 3 Q CV, 4 keyboard pitch, 5 keyboard gate, 6 keyboard trigger |
| D165 | value for the selected DAC (gate/trigger: 0 or 1) |

Model: `sim/devices/synth.py` `ControlVoltages` (records the last value per
DAC; reads halt). Test: `tests/sim/test_synth.py`.

**Evidence:** NED `Able/SYNRSOU/06-MAIN/390-VOLT` (`6dfe79d16413`: "WRITE
OUT LP FILTER CV", "HP CV", "BP CV", "Q CV"), `06-MAIN/308-STR8` ("SELECT
KEYBOARD PITCH DAC"), `10-INT/144-TIM3` (`2e820d8ef02d`: gate 5, trigger 6);
SYSLITS `o#d164`. Release L ORK-LM writes D164 = 0–3 with D165 = 250, 0,
250, 4224 about 4.3 s after start, although 03-SYSTD's options word does not
set `o#d164`. **[OBS]**
