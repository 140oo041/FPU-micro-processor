# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is the firmware developer working at a Windows PC with the ESP32-based FPU controller connected over USB serial.

## Product Purpose

Provide an easy PC-side interface for composing FPU operations, sending the UART commands understood by `main/main.c`, triggering the SPI transfer, and inspecting firmware output. Success means routine board interaction does not require hand-encoding bytes or using a serial terminal.

## Positioning

The application translates human-readable floating-point operations into the project's exact bfloat16 UART command format while keeping the transmitted bytes visible for debugging.

## Operating Context

The application runs locally on the developer's PC beside the ESP-IDF firmware workflow. It connects to a USB serial port at 115200 baud and operates as a focused bench tool.

## Capabilities and Constraints

- Use the command protocol implemented in `main/main.c`.
- Support binary and unary FPU operations, raw queue bytes, SPI transfer, and cancel commands.
- Show available serial ports, connection state, transmitted bytes, and device output.
- Run as a Python-hosted desktop webview; serial access stays in Python rather than the browser.
- Keep the firmware untouched unless a separate firmware change is requested.

## Evidence on Hand

- UART command handling: `main/main.c`
- FPU frame construction: `main/frame.c`
- Existing PC-side encoding reference: `generate_fpu_ops.py`
- No benchmarks, external users, or commercial claims are established.

## Product Principles

- Make the common operation-to-transfer loop immediate.
- Keep wire-level bytes visible and copyable.
- Surface connection and protocol errors plainly.
- Favor local, dependency-light operation suitable for a development bench.

