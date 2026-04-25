# Channel

> **Tooltip:** Per-call hint (production / staging / shadow / challenger / champion / validation) that drives default write behavior.

## Definition

A per-call enum that tells the runtime how serious this run is. Defaults for write_targets: production / champion = write; staging / shadow / challenger = log-only; validation = always log-only. Combine with write_mode for finer control.

## See also

- [Write Mode](write-mode.md)
- [Write Target](write-target.md)
- [Run Purpose](run-purpose.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
