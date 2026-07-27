---
name: FPU Bench Console
description: A tactile scientific-calculator interface for operating and inspecting the FPU link.
colors:
  desktop: "#d7dad4"
  graphite: "#202827"
  graphite-raised: "#2a3432"
  seam: "#46514e"
  warm-key: "#e7e3d8"
  key-edge: "#b6b2a8"
  ink: "#1b2422"
  lcd: "#c9d4ad"
  lcd-ink: "#17231b"
  lcd-muted: "#42503e"
  function-blue: "#345f79"
  transmit-amber: "#d99235"
  error: "#d86355"
  connected: "#70ad82"
typography:
  title:
    fontFamily: "Segoe UI Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.15
  body:
    fontFamily: "Segoe UI Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  readout:
    fontFamily: "Consolas, Cascadia Mono, SFMono-Regular, monospace"
    fontSize: "clamp(24px, 4vw, 40px)"
    fontWeight: 700
    lineHeight: 1.1
  label:
    fontFamily: "Segoe UI Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 650
    lineHeight: 1.45
rounded:
  key: "7px"
  field: "8px"
  chassis: "18px"
spacing:
  tight: "9px"
  control: "12px"
  panel: "18px"
components:
  button-primary:
    backgroundColor: "{colors.transmit-amber}"
    textColor: "{colors.ink}"
    rounded: "{rounded.key}"
    padding: "9px 14px"
    height: "50px"
  button-secondary:
    backgroundColor: "{colors.function-blue}"
    textColor: "#ffffff"
    rounded: "{rounded.key}"
    padding: "9px 14px"
    height: "42px"
  input:
    backgroundColor: "{colors.warm-key}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "9px 11px"
    height: "42px"
---

# Design System: FPU Bench Console

## Overview

**Creative North Star: "The Bench Calculator"**

The interface borrows the operational confidence of a serious handheld scientific calculator: a durable dark chassis, a broad low-glare readout, tightly grouped controls, and keys that communicate function through position as much as color. It is an instrument rather than a dashboard; the operator should understand its state without scanning decorative containers.

Protocol detail remains part of the working surface. Encoded bytes, port state, and device output are not hidden behind friendly abstractions. Motion is brief and mechanical: keys depress, indicators change state, and new wire traffic advances through a compact tape.

**Key Characteristics:**

- Tactile, compact operation panel
- Wide LCD-like protocol readout
- Explicit labels and persistent connection state
- Instrument-grade density with generous hit targets

## Colors

Use a restrained instrument palette: graphite chassis and warm light keycaps, a desaturated green-gray display field, blue secondary functions, and one amber action color. The screen is designed for a developer seated at a normally lit PC workbench, so strong contrast matters without turning the entire application dark.

- **Function Blue:** Secondary operations, selected functions, and connected actions.
- **Transmit Amber:** The singular send action.
- **LCD Green-Gray:** Encoded command preview and formula field.
- **Graphite:** Chassis and panel structure.
- **Warm Key:** Inputs, operation keys, and neutral physical controls.

**The Indicator Rule.** Saturated color communicates action or live state; it is not ambient decoration.

## Typography

Use the operating system's workhorse UI family for controls and a crisp system monospace for bytes, values, and firmware output. Numerals should remain tabular wherever columns need to align. Labels are concise and never spaced so widely that technical terms become harder to scan.

**The Readout Rule.** Wire values and device output always use monospace; explanatory text never needs to imitate a terminal.

## Layout

The desktop view is one instrument chassis with a compact connection strip, a dominant protocol readout, and a two-column working area: operand/operation controls on the left and serial output on the right. The primary action sits beside the operation keys rather than in a detached footer.

At narrow widths the controls stack above the console while preserving action order. Hit targets remain at least 40 pixels tall and the byte readout scrolls horizontally rather than wrapping ambiguous groups.

## Elevation & Depth

Depth is structural and shallow. The outer chassis is lifted once from the desktop; keycaps use a small lower edge and active press displacement. LCD and console fields are inset through inner borders, not glow. Avoid layered floating cards.

## Shapes

Use modestly softened corners on the chassis and readouts, with slightly tighter corners on keycaps. Controls should feel manufactured and aligned, not pill-shaped. Connection indicators may be circular because they represent lamps.

## Components

### Buttons

- Neutral keys use the warm-key surface with a visible lower edge and a two-pixel press displacement.
- Function keys use blue; only the selected operation receives an inset selection line.
- The amber button is reserved for transmitting an operation.
- All buttons use a high-contrast three-pixel focus outline.

### Inputs / Fields

- Operand and serial fields use warm-key surfaces with dark ink.
- Protocol readouts use the inset LCD surface and monospace values.
- Invalid values replace the byte preview with a specific encoding error.

### Connection Rail

The persistent top rail contains product identity, a lamp-style status indicator, port, baud, refresh, and connect controls. Connected state locks port configuration until the user disconnects.

### Wire Monitor

Incoming, outgoing, system, and error messages use distinct text colors within one inset console. The log is additive, scrolls to current activity, and has an explicit clear action.

## Do's and Don'ts

### Do:

- **Do** make the current port state and transmitted byte sequence visible at all times.
- **Do** group operation keys by function and preserve familiar mathematical labels.
- **Do** make keyboard focus as legible as pointer hover.

### Don't:

- **Don't** turn every section into a floating card.
- **Don't** use glow, glass, or decorative gradients in place of instrument structure.
- **Don't** hide protocol errors behind generic failure messages.
