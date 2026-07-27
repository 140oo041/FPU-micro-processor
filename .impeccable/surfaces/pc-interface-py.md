---
version: 1
slug: "pc-interface-py"
primary_target: "pc_interface.py"
related_targets: []
---

Scope: `pc_interface.py` desktop webview. Mode: Operate.

Audience: firmware developer at a PC workbench.
Job: connect to the ESP32, compose one FPU operation, inspect its encoded bytes, transmit it, trigger SPI, and read firmware output.
Task success: the common operation-to-transfer loop is obvious and connection/protocol failures are actionable.
Content constraints: use only commands implemented in `main/main.c`; do not imply calculated result decoding that the firmware does not provide.

Direction: Bench Calculator, drawing from scientific calculators and embedded lab instruments.
Memorable moment: every operation updates a broad LCD-like readout with the exact outgoing bytes before the tactile SEND key transmits them.

Unresolved: actual serial hardware behavior cannot be validated without the connected board.
