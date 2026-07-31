#!/usr/bin/env python3
"""Native desktop WebView for the ESP32 FPU UART interface.

Install dependencies:
    python -m pip install pyserial pywebview

Run:
    python pc_interface.py
"""

from __future__ import annotations

import argparse
import re
import struct
import threading
from collections import deque
from typing import Any, Optional, Sequence


BINARY_COMMANDS = {"add": b"A", "sub": b"S", "mul": b"M", "div": b"D"}
UNARY_COMMANDS = {"abs": b"B", "neg": b"N", "slt": b"L", "nop": b"O"}
SPI_OPCODES = {
    "add": 0b000,
    "sub": 0b001,
    "mul": 0b010,
    "div": 0b011,
    "neg": 0b100,
    "abs": 0b101,
    "slt": 0b110,
    "nop": 0b111,
}
TX_BUFFER_LINE = re.compile(r"TX\[(\d+)\]\s*=\s*0x([0-9A-Fa-f]{2})")
RX_BUFFER_LINE = re.compile(r"RX\[(\d+)\]\s*=\s*0x([0-9A-Fa-f]{2})")


class CommandError(ValueError):
    """A command could not be encoded."""


def bfloat16_bytes(value: float) -> bytes:
    """Return the upper 16 bits of an IEEE-754 single-precision float."""
    try:
        return struct.pack(">f", float(value))[:2]
    except (ValueError, TypeError, OverflowError, struct.error) as error:
        raise CommandError(f"{value!r} is not a valid float32 value") from error


def parse_acc(value: Any) -> int:
    try:
        acc = int(value)
    except (TypeError, ValueError) as error:
        raise CommandError("Accumulator must be 0 or 1") from error
    if acc not in (0, 1):
        raise CommandError("Accumulator must be 0 or 1")
    return acc


def crc8_autosar(data: bytes) -> int:
    """Calculate CRC-8/AUTOSAR (poly 0x2F, init/xorout 0xFF)."""
    crc = 0xFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x2F) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ 0xFF


def encode_operation(
    operation: str, operand_a: Any, operand_b: Any = None, acc: Any = 0
) -> bytes:
    operation = operation.lower()
    acc_byte = bytes([parse_acc(acc)])
    if operation in BINARY_COMMANDS:
        if operand_b in (None, ""):
            raise CommandError(f"{operation.upper()} requires operands A and B")
        return (
            BINARY_COMMANDS[operation]
            + bfloat16_bytes(operand_a)
            + bfloat16_bytes(operand_b)
            + acc_byte
        )
    if operation in UNARY_COMMANDS:
        return UNARY_COMMANDS[operation] + bfloat16_bytes(operand_a) + acc_byte
    raise CommandError(f"Unknown operation: {operation}")


def encode_spi_frame(
    operation: str,
    operand_a: Any,
    operand_b: Any = None,
    acc: Any = 0,
    tag: int = 0,
) -> bytes:
    """Encode the FPU frame that firmware queues after consuming a UART command."""
    operation = operation.lower()
    if operation not in SPI_OPCODES:
        raise CommandError(f"Unknown operation: {operation}")
    if operation in BINARY_COMMANDS and operand_b in (None, ""):
        raise CommandError(f"{operation.upper()} requires operands A and B")

    binary_flag = int(operation in BINARY_COMMANDS)
    header = (
        (SPI_OPCODES[operation] << 5)
        | (parse_acc(acc) << 4)
        | (binary_flag << 3)
        | (tag & 0x07)
    )
    frame = bytearray([header])
    frame.extend(bfloat16_bytes(operand_a))
    if binary_flag:
        frame.extend(bfloat16_bytes(operand_b))
    frame.append(crc8_autosar(frame))
    return bytes(frame)


def encode_raw_queue(values: Sequence[Any]) -> bytes:
    if not values:
        raise CommandError("Enter at least one raw byte")
    if len(values) > 127:
        raise CommandError("main.c accepts at most 127 queued bytes per command")
    encoded = bytearray(b"P")
    for value in values:
        try:
            byte = int(str(value), 0)
        except ValueError as error:
            raise CommandError(f"Invalid byte: {value!r}") from error
        if not 0 <= byte <= 255:
            raise CommandError(f"Byte out of range: {value!r}")
        encoded.append(byte)
    return bytes(encoded)


def response(ok: bool, **data: Any) -> dict[str, Any]:
    return {"ok": ok, **data}


class FpuApi:
    """Methods exposed to JavaScript by pywebview."""

    def __init__(self, initial_port: Optional[str] = None) -> None:
        self.initial_port = initial_port
        self._serial: Any = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._events: deque[dict[str, str]] = deque(maxlen=1000)
        self._events_lock = threading.Lock()
        self._serial_lock = threading.Lock()
        self._rx_text_buffer = ""
        self._tag = 0

    def _event(self, kind: str, message: str) -> None:
        with self._events_lock:
            self._events.append({"kind": kind, "message": message})

    def list_ports(self) -> dict[str, Any]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return response(False, error="pyserial is not installed")
        ports = [
            {"device": port.device, "description": port.description}
            for port in list_ports.comports()
        ]
        return response(True, ports=ports, initialPort=self.initial_port)

    def connect(self, port: str, baud: Any = 115200) -> dict[str, Any]:
        if not port:
            return response(False, error="Select a serial port first")
        try:
            import serial
        except ImportError:
            return response(
                False,
                error="pyserial is missing. Run: python -m pip install pyserial",
            )
        try:
            baud_value = int(baud)
            if baud_value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return response(False, error="Baud rate must be a positive integer")

        self.disconnect()
        try:
            self._serial = serial.Serial(port, baud_value, timeout=0.1)
        except serial.SerialException as error:
            return response(False, error=f"Could not open {port}: {error}")

        self._stop.clear()
        self._rx_text_buffer = ""
        self._tag = 0
        self._reader = threading.Thread(target=self._read_serial, daemon=True)
        self._reader.start()
        self._event("system", f"Connected to {port} at {baud_value} baud")
        self._event("connection", "connected")
        return response(True, port=port, baud=baud_value)

    def disconnect(self) -> dict[str, Any]:
        serial_port = self._serial
        self._serial = None
        self._stop.set()
        if serial_port is not None:
            port_name = getattr(serial_port, "port", "serial port")
            try:
                serial_port.close()
            except Exception:
                pass
            self._event("system", f"Disconnected from {port_name}")
            self._event("connection", "disconnected")
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.4)
        self._reader = None
        return response(True)

    def _read_serial(self) -> None:
        while not self._stop.is_set():
            serial_port = self._serial
            if serial_port is None:
                return
            try:
                waiting = serial_port.in_waiting
                data = serial_port.read(waiting or 1)
            except Exception as error:
                if not self._stop.is_set():
                    self._event("error", f"Serial read failed: {error}")
                    self.disconnect()
                return
            if data:
                self._route_serial_text(
                    data.decode("utf-8", errors="backslashreplace")
                )

    def _route_serial_text(self, text: str) -> None:
        """Route firmware TX-buffer dump lines away from the general console."""
        self._rx_text_buffer += text
        lines = self._rx_text_buffer.split("\n")
        self._rx_text_buffer = lines.pop()

        for line in lines:
            line += "\n"
            for kind, pattern in (
                ("tx_buffer", TX_BUFFER_LINE),
                ("rx_buffer", RX_BUFFER_LINE),
            ):
                match = pattern.search(line)
                if not match:
                    continue
                index = int(match.group(1))
                if 0 <= index < 256:
                    self._event(kind, f"{index}:{match.group(2).upper()}")
                    break
            else:
                self._event("rx", line)

    def _send(self, data: bytes) -> dict[str, Any]:
        if self._serial is None or not getattr(self._serial, "is_open", False):
            return response(False, error="Connect to the ESP32 before transmitting")
        try:
            with self._serial_lock:
                self._serial.write(data)
                self._serial.flush()
        except Exception as error:
            self._event("error", f"Serial write failed: {error}")
            return response(False, error=f"Serial write failed: {error}")
        hex_data = data.hex(" ").upper()
        self._event("tx", hex_data)
        return response(True, hex=hex_data, length=len(data))

    def preview_operation(
        self, operation: str, operand_a: Any, operand_b: Any, acc: Any
    ) -> dict[str, Any]:
        try:
            uart_data = encode_operation(operation, operand_a, operand_b, acc)
            spi_data = encode_spi_frame(
                operation, operand_a, operand_b, acc, self._tag
            )
        except CommandError as error:
            return response(False, error=str(error))
        return response(
            True,
            hex=uart_data.hex(" ").upper(),
            length=len(uart_data),
            uartHex=uart_data.hex(" ").upper(),
            uartLength=len(uart_data),
            spiHex=spi_data.hex(" ").upper(),
            spiLength=len(spi_data),
            tag=self._tag,
        )

    def send_operation(
        self, operation: str, operand_a: Any, operand_b: Any, acc: Any
    ) -> dict[str, Any]:
        try:
            uart_data = encode_operation(operation, operand_a, operand_b, acc)
            spi_data = encode_spi_frame(
                operation, operand_a, operand_b, acc, self._tag
            )
        except CommandError as error:
            return response(False, error=str(error))
        result = self._send(uart_data)
        if result["ok"]:
            result.update(
                uartHex=uart_data.hex(" ").upper(),
                uartLength=len(uart_data),
                spiHex=spi_data.hex(" ").upper(),
                spiLength=len(spi_data),
                tag=self._tag,
            )
            self._tag = (self._tag + 1) % 8
        return result

    def send_raw(self, text: str) -> dict[str, Any]:
        values = text.replace(",", " ").split()
        try:
            data = encode_raw_queue(values)
        except CommandError as error:
            return response(False, error=str(error))
        return self._send(data)

    def send_control(self, command: str) -> dict[str, Any]:
        commands = {"transfer": b"R", "cancel": b"X", "view": b"V"}
        if command not in commands:
            return response(False, error=f"Unknown control command: {command}")
        return self._send(commands[command])

    def drain_events(self) -> dict[str, Any]:
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
        return response(True, events=events)

    def close(self) -> None:
        self.disconnect()


HTML = r"""
<!--
THESIS: A serious bench calculator turns float operations into visible wire commands; it refuses the generic dashboard grid.
OWN-WORLD: Graphite instrument chassis, warm keycaps, green-gray LCD fields, blue secondary functions, and one amber transmit key.
STORY: Connect the board, compose an operation, verify its bytes, transmit, trigger SPI, and inspect firmware output without leaving one surface.
FIRST VIEWPORT: Connection rail above a wide protocol readout; operation controls fill the left bench and the live serial console fills the right. SEND sits beside the operation keypad.
FORM: Scientific-calculator panel, fifth grounded direction; compact two-column staging; seed bcefcf53.
-->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FPU Bench Console</title>
  <style>
    :root {
      color-scheme: light;
      --desk: #d7dad4;
      --chassis: #202827;
      --chassis-hi: #2a3432;
      --seam: #46514e;
      --key: #e7e3d8;
      --key-edge: #b6b2a8;
      --key-text: #1b2422;
      --display: #c9d4ad;
      --display-ink: #17231b;
      --display-muted: #42503e;
      --blue: #345f79;
      --blue-hi: #427593;
      --amber: #d99235;
      --amber-hi: #eeaa50;
      --paper: #f3f2ec;
      --muted: #aeb8b4;
      --danger: #d86355;
      --success: #70ad82;
      --radius-chassis: 18px;
      --radius-field: 8px;
      --radius-key: 7px;
      --shadow-chassis: 0 18px 48px rgba(23, 30, 28, .24);
      --font-ui: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
      --font-mono: Consolas, "Cascadia Mono", "SFMono-Regular", monospace;
    }

    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      background: var(--desk);
      color: var(--paper);
      font-family: var(--font-ui);
      font-size: 15px;
      line-height: 1.45;
    }
    button, input, select { font: inherit; }
    button { touch-action: manipulation; }
    .app {
      width: min(1240px, calc(100% - 32px));
      margin: 16px auto;
      overflow: hidden;
      background: var(--chassis);
      border-radius: var(--radius-chassis);
      box-shadow: var(--shadow-chassis);
    }
    .connection-rail {
      min-height: 72px;
      display: grid;
      grid-template-columns: minmax(210px, 1fr) minmax(180px, 320px) 112px auto auto;
      align-items: center;
      gap: 10px;
      padding: 12px 18px;
      background: var(--chassis-hi);
      border-bottom: 1px solid var(--seam);
    }
    .identity { min-width: 0; }
    .identity h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
      letter-spacing: -.01em;
    }
    .identity p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .lamp {
      width: 8px;
      height: 8px;
      flex: 0 0 auto;
      border-radius: 50%;
      background: #76807d;
      box-shadow: inset 0 0 0 1px rgba(0,0,0,.28);
    }
    .status.connected .lamp { background: var(--success); }
    .status.error .lamp { background: var(--danger); }
    .field-label {
      display: block;
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }
    select, input[type="text"], input[type="number"] {
      width: 100%;
      min-height: 42px;
      padding: 9px 11px;
      color: var(--key-text);
      background: var(--key);
      border: 1px solid var(--key-edge);
      border-radius: var(--radius-field);
      outline: 0;
    }
    select:focus-visible, input:focus-visible, button:focus-visible {
      outline: 3px solid #8ab9d3;
      outline-offset: 2px;
    }
    .rail-field { min-width: 0; }
    .button {
      min-height: 42px;
      padding: 9px 14px;
      border: 0;
      border-radius: var(--radius-key);
      color: var(--key-text);
      background: var(--key);
      box-shadow: 0 3px 0 var(--key-edge);
      cursor: pointer;
      font-weight: 700;
      transition: background-color 140ms ease-out, transform 90ms ease-out, box-shadow 90ms ease-out;
    }
    .button:hover { background: #f3efe4; }
    .button:active { transform: translateY(2px); box-shadow: 0 1px 0 var(--key-edge); }
    .button:disabled { cursor: not-allowed; opacity: .48; box-shadow: none; }
    .button.secondary { color: #fff; background: var(--blue); box-shadow-color: #203d4e; }
    .button.secondary:hover { background: var(--blue-hi); }
    .button.ghost { color: var(--paper); background: transparent; border: 1px solid var(--seam); box-shadow: none; }
    .button.ghost:hover { background: rgba(255,255,255,.06); }
    .readout-wrap { padding: 18px 18px 0; }
    .readout {
      position: relative;
      min-height: 164px;
      padding: 18px 20px 16px;
      overflow: hidden;
      color: var(--display-ink);
      background: var(--display);
      border: 2px solid #111716;
      border-radius: 10px;
      box-shadow: inset 0 3px 10px rgba(24, 38, 29, .24);
    }
    .readout-top { display: flex; justify-content: space-between; gap: 16px; }
    .operation-name { color: var(--display-muted); font-size: 12px; font-weight: 800; }
    .formula {
      margin-top: 7px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: clamp(24px, 4vw, 40px);
      font-weight: 700;
      line-height: 1.1;
      letter-spacing: -.03em;
    }
    .wire-row {
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin-top: 14px;
      min-width: 0;
    }
    .wire-row + .wire-row { margin-top: 8px; }
    .wire-label { flex: 0 0 64px; color: var(--display-muted); font-size: 10px; font-weight: 800; }
    .wire-bytes {
      overflow-x: auto;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: 16px;
      font-weight: 700;
      scrollbar-width: thin;
    }
    .bench {
      display: grid;
      grid-template-columns: minmax(390px, .82fr) minmax(420px, 1.18fr);
      gap: 1px;
      margin-top: 18px;
      background: var(--seam);
      border-top: 1px solid var(--seam);
    }
    .control-panel, .monitor { min-width: 0; background: var(--chassis); padding: 20px 18px 22px; }
    .panel-heading { margin: 0 0 14px; font-size: 14px; }
    .operand-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .operand.disabled { opacity: .42; }
    .operation-pad {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 9px;
      margin-top: 18px;
    }
    .op-key { min-height: 48px; font-family: var(--font-mono); font-size: 16px; }
    .op-key[aria-pressed="true"] {
      color: #fff;
      background: var(--blue);
      box-shadow: inset 0 0 0 2px #79a8c1, 0 3px 0 #203d4e;
    }
    .op-key small { display: block; margin-top: 1px; font-family: var(--font-ui); font-size: 9px; font-weight: 650; }
    .action-row { display: grid; grid-template-columns: 1fr 1.45fr; gap: 10px; margin-top: 18px; }
    .acc-toggle {
      min-height: 50px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 0 12px;
      color: var(--paper);
      background: #171d1c;
      border: 1px solid var(--seam);
      border-radius: var(--radius-key);
      cursor: pointer;
    }
    .acc-toggle input { position: absolute; opacity: 0; pointer-events: none; }
    .toggle-track { width: 34px; height: 18px; padding: 3px; border-radius: 10px; background: #69736f; }
    .toggle-knob { width: 12px; height: 12px; border-radius: 50%; background: #fff; transition: transform 150ms ease-out; }
    .acc-toggle input:checked + .toggle-track { background: var(--blue-hi); }
    .acc-toggle input:checked + .toggle-track .toggle-knob { transform: translateX(16px); }
    .acc-toggle:focus-within { outline: 3px solid #8ab9d3; outline-offset: 2px; }
    .send-button {
      min-height: 50px;
      background: var(--amber);
      box-shadow-color: #945d1e;
      font-size: 15px;
    }
    .send-button:hover { background: var(--amber-hi); }
    .bus-actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
    .raw-queue { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--seam); }
    .raw-row { display: grid; grid-template-columns: 1fr auto; gap: 10px; }
    .hint { margin: 7px 0 0; color: var(--muted); font-size: 11px; }
    .monitor { display: flex; flex-direction: column; min-height: 420px; }
    .monitor-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px 16px; }
    .monitor-head .panel-heading { margin: 0; }
    .monitor-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; }
    .view-switch {
      display: flex;
      gap: 2px;
      padding: 2px;
      background: #171d1c;
      border: 1px solid var(--seam);
      border-radius: var(--radius-key);
    }
    .view-tab {
      min-height: 40px;
      padding: 7px 10px;
      color: var(--muted);
      background: transparent;
      border: 0;
      border-radius: var(--radius-key);
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
    }
    .view-tab:hover { color: var(--paper); background: rgba(255,255,255,.05); }
    .view-tab[aria-selected="true"] { color: var(--paper); background: var(--blue); }
    .monitor-view[hidden] { display: none; }
    .console {
      flex: 0 1 auto;
      height: clamp(300px, 44vh, 480px);
      min-height: 0;
      margin-top: 14px;
      padding: 14px;
      overflow-x: hidden;
      overflow-y: auto;
      overscroll-behavior: contain;
      scrollbar-gutter: stable;
      color: var(--paper);
      background: #111716;
      border: 1px solid #0b0f0e;
      border-radius: var(--radius-field);
      box-shadow: inset 0 3px 10px rgba(0,0,0,.34);
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .console:focus-visible { outline: 3px solid #8ab9d3; outline-offset: 2px; }
    .console-line { display: block; }
    .console-line.tx { color: #e6b670; }
    .console-line.rx { color: #bcd3c3; }
    .console-line.system { color: #8fbbd2; }
    .console-line.error { color: #ef8d81; }
    .console-empty { color: #84908b; }
    .buffer-view {
      height: clamp(300px, 44vh, 480px);
      min-height: 0;
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      color: #dce5df;
      background: #111716;
      border: 1px solid #0b0f0e;
      border-radius: var(--radius-field);
      box-shadow: inset 0 3px 10px rgba(0,0,0,.34);
    }
    .buffer-summary {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      color: var(--muted);
      border-bottom: 1px solid var(--seam);
      font-size: 11px;
    }
    .buffer-summary strong { color: var(--paper); font-size: 11px; }
    .buffer-scroll { min-height: 0; overflow: auto; scrollbar-gutter: stable; }
    .buffer-scroll:focus-visible { outline: 3px solid #8ab9d3; outline-offset: -3px; }
    .buffer-table {
      width: max-content;
      min-width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-family: var(--font-mono);
      font-size: 11px;
      font-variant-numeric: tabular-nums;
      text-align: center;
    }
    .buffer-table th, .buffer-table td {
      min-width: 30px;
      height: 27px;
      padding: 4px 6px;
      border-right: 1px solid var(--seam);
      border-bottom: 1px solid var(--seam);
    }
    .buffer-table thead th {
      position: sticky;
      top: 0;
      z-index: 2;
      color: var(--muted);
      background: var(--chassis);
    }
    .buffer-table tbody th {
      position: sticky;
      left: 0;
      z-index: 1;
      color: var(--muted);
      background: var(--chassis);
      text-align: right;
    }
    .buffer-table thead th:first-child { left: 0; z-index: 3; }
    .buffer-table td { color: var(--muted); }
    .buffer-table td.filled { color: var(--amber); background: #151c1a; }
    .toast {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 10;
      max-width: min(420px, calc(100vw - 44px));
      padding: 12px 14px;
      color: #fff;
      background: #6e3029;
      border-radius: 8px;
      box-shadow: 0 10px 30px rgba(0,0,0,.25);
      transform: translateY(18px);
      opacity: 0;
      pointer-events: none;
      transition: transform 180ms cubic-bezier(.2,.8,.2,1), opacity 180ms ease-out;
    }
    .toast.visible { transform: translateY(0); opacity: 1; }
    @media (max-width: 900px) {
      .connection-rail { grid-template-columns: 1fr 1fr auto; }
      .identity { grid-column: 1 / -1; }
      .rail-baud { display: none; }
      .bench { grid-template-columns: 1fr; }
      .monitor { min-height: 360px; }
    }
    @media (max-width: 560px) {
      .app { width: 100%; min-height: 100vh; margin: 0; border-radius: 0; }
      .connection-rail { grid-template-columns: 1fr auto; padding: 12px; }
      .rail-field { grid-column: 1 / -1; }
      .readout-wrap { padding: 12px 12px 0; }
      .control-panel, .monitor { padding: 18px 12px; }
      .operand-grid { grid-template-columns: 1fr; }
      .operation-pad { grid-template-columns: repeat(2, 1fr); }
      .readout { min-height: 126px; padding: 16px; }
      .monitor-head { align-items: flex-start; flex-direction: column; }
      .monitor-tools { width: 100%; justify-content: space-between; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header class="connection-rail">
      <div class="identity">
        <h1>FPU Bench Console</h1>
        <div id="connectionStatus" class="status" role="status" aria-live="polite">
          <span class="lamp" aria-hidden="true"></span><span id="statusText">Disconnected</span>
        </div>
      </div>
      <label class="rail-field">
        <span class="field-label">Serial port</span>
        <select id="portSelect" aria-label="Serial port"><option value="">Scanning…</option></select>
      </label>
      <label class="rail-baud">
        <span class="field-label">Baud</span>
        <select id="baudSelect" aria-label="Baud rate">
          <option>115200</option>
        </select>
      </label>
      <button id="refreshButton" class="button ghost" type="button">Refresh</button>
      <button id="connectButton" class="button secondary" type="button">Connect</button>
    </header>

    <section class="readout-wrap" aria-labelledby="readoutTitle">
      <div class="readout">
        <div class="readout-top">
          <span id="readoutTitle" class="operation-name">ADD · BINARY</span>
          <span id="frameLength" class="operation-name">UART 6B · SPI 6B · TAG 0</span>
        </div>
        <div id="formula" class="formula">1.0 + 2.0</div>
        <div class="wire-row">
          <span class="wire-label">UART TX</span>
          <span id="wireBytes" class="wire-bytes" role="status" aria-live="polite">41 3F 80 40 00 00</span>
        </div>
        <div class="wire-row">
          <span class="wire-label" title="Expected FPU frame derived locally from the UART command">SPI FRAME</span>
          <span id="spiWireBytes" class="wire-bytes">08 3F 80 40 00</span>
        </div>
      </div>
    </section>

    <div class="bench">
      <section class="control-panel" aria-labelledby="operationHeading">
        <h2 id="operationHeading" class="panel-heading">Compose operation</h2>
        <div class="operand-grid">
          <label class="operand">
            <span class="field-label">Operand A</span>
            <input id="operandA" type="number" step="any" value="1.0" inputmode="decimal">
          </label>
          <label id="operandBWrap" class="operand">
            <span class="field-label">Operand B</span>
            <input id="operandB" type="number" step="any" value="2.0" inputmode="decimal">
          </label>
        </div>

        <div id="operationPad" class="operation-pad" aria-label="FPU operation">
          <button class="button op-key" type="button" data-op="add" aria-pressed="true">+<small>ADD</small></button>
          <button class="button op-key" type="button" data-op="sub" aria-pressed="false">−<small>SUB</small></button>
          <button class="button op-key" type="button" data-op="mul" aria-pressed="false">×<small>MUL</small></button>
          <button class="button op-key" type="button" data-op="div" aria-pressed="false">÷<small>DIV</small></button>
          <button class="button op-key" type="button" data-op="abs" aria-pressed="false">|x|<small>ABS</small></button>
          <button class="button op-key" type="button" data-op="neg" aria-pressed="false">±<small>NEG</small></button>
          <button class="button op-key" type="button" data-op="slt" aria-pressed="false">&lt;<small>SLT</small></button>
          <button class="button op-key" type="button" data-op="nop" aria-pressed="false">→<small>NOP</small></button>
        </div>

        <div class="action-row">
          <label class="acc-toggle">
            <span>Accumulator</span>
            <input id="accumulator" type="checkbox"><span class="toggle-track"><span class="toggle-knob"></span></span>
          </label>
          <button id="sendButton" class="button send-button" type="button" disabled>Send operation</button>
        </div>
        <div class="bus-actions">
          <button id="transferButton" class="button secondary" type="button" disabled>SPI transfer</button>
          <button id="viewBufferButton" class="button" type="button" disabled>View TX buffer</button>
          <button id="cancelButton" class="button ghost" type="button" disabled>Cancel</button>
        </div>

        <div class="raw-queue">
          <label for="rawBytes" class="field-label">Raw queue bytes</label>
          <div class="raw-row">
            <input id="rawBytes" type="text" placeholder="0x28 0x3F 0x80" spellcheck="false">
            <button id="queueButton" class="button" type="button" disabled>Queue</button>
          </div>
          <p class="hint">Space- or comma-separated decimal, hex, or binary bytes. The app prefixes the firmware’s P command.</p>
        </div>
      </section>

      <section class="monitor" aria-labelledby="monitorHeading">
        <div class="monitor-head">
          <h2 id="monitorHeading" class="panel-heading">Device inspection</h2>
          <div class="monitor-tools">
            <div class="view-switch" role="tablist" aria-label="Device inspection view">
              <button id="consoleTab" class="view-tab" type="button" role="tab" aria-selected="true" aria-controls="consoleView">Console</button>
              <button id="txTab" class="view-tab" type="button" role="tab" aria-selected="false" aria-controls="txView" tabindex="-1">TX buffer</button>
              <button id="rxTab" class="view-tab" type="button" role="tab" aria-selected="false" aria-controls="rxView" tabindex="-1">RX buffer</button>
            </div>
            <button id="clearButton" class="button ghost" type="button">Clear output</button>
          </div>
        </div>
        <div id="consoleView" class="monitor-view" role="tabpanel" aria-labelledby="consoleTab">
          <div id="console" class="console" role="log" aria-label="Serial traffic and firmware output" aria-live="polite" aria-relevant="additions" tabindex="0">
            <span class="console-empty">Connect a serial port to begin. Outgoing commands and firmware output appear here.</span>
          </div>
        </div>
        <div id="txView" class="buffer-view monitor-view" role="tabpanel" aria-labelledby="txTab" hidden>
          <div class="buffer-summary">
            <strong>Transmit ring · 256 bytes</strong>
            <span id="txBufferStatus" role="status" aria-live="polite">No capture yet</span>
          </div>
          <div class="buffer-scroll" tabindex="0" aria-label="Transmit buffer bytes">
            <table id="txBufferTable" class="buffer-table" aria-label="TX buffer indexed hexadecimal bytes"></table>
          </div>
        </div>
        <div id="rxView" class="buffer-view monitor-view" role="tabpanel" aria-labelledby="rxTab" hidden>
          <div class="buffer-summary">
            <strong>Receive ring · 256 bytes</strong>
            <span id="rxBufferStatus" role="status" aria-live="polite">No capture yet</span>
          </div>
          <div class="buffer-scroll" tabindex="0" aria-label="Receive buffer bytes">
            <table id="rxBufferTable" class="buffer-table" aria-label="RX buffer indexed hexadecimal bytes"></table>
          </div>
        </div>
      </section>
    </div>
  </main>
  <div id="toast" class="toast" role="alert"></div>

  <script>
    const state = {
      operation: 'add', connected: false, previewTimer: null, eventTimer: null,
      monitorView: 'console', txBuffer: new Map(), rxBuffer: new Map()
    };
    const binary = new Set(['add', 'sub', 'mul', 'div']);
    const symbols = { add: '+', sub: '−', mul: '×', div: '÷', abs: 'abs', neg: '−', slt: 'slt', nop: 'nop' };
    const $ = id => document.getElementById(id);

    function showError(message) {
      const toast = $('toast');
      toast.textContent = message;
      toast.classList.add('visible');
      clearTimeout(showError.timer);
      showError.timer = setTimeout(() => toast.classList.remove('visible'), 4200);
    }

    function setConnection(connected, text, isError = false) {
      state.connected = connected;
      const status = $('connectionStatus');
      status.classList.toggle('connected', connected);
      status.classList.toggle('error', isError);
      $('statusText').textContent = text;
      $('connectButton').textContent = connected ? 'Disconnect' : 'Connect';
      $('portSelect').disabled = connected;
      $('baudSelect').disabled = connected;
      ['sendButton', 'transferButton', 'viewBufferButton', 'cancelButton', 'queueButton'].forEach(id => $(id).disabled = !connected);
    }

    function appendConsole(kind, message) {
      const consoleElement = $('console');
      const distanceFromBottom = consoleElement.scrollHeight - consoleElement.scrollTop - consoleElement.clientHeight;
      const followLatest = distanceFromBottom < 36;
      const empty = consoleElement.querySelector('.console-empty');
      if (empty) empty.remove();
      const line = document.createElement('span');
      line.className = `console-line ${kind}`;
      const prefix = { tx: 'TX › ', rx: 'RX ‹ ', system: '• ', error: '! ' }[kind] || '';
      line.textContent = prefix + message;
      consoleElement.appendChild(line);
      if (followLatest) consoleElement.scrollTop = consoleElement.scrollHeight;
    }

    function buildBufferTable(kind) {
      const table = $(`${kind}BufferTable`);
      const label = kind.toUpperCase();
      const head = document.createElement('thead');
      const headingRow = document.createElement('tr');
      const addressHeading = document.createElement('th');
      addressHeading.scope = 'col';
      addressHeading.textContent = 'ADDR';
      headingRow.appendChild(addressHeading);
      for (let column = 0; column < 16; column += 1) {
        const heading = document.createElement('th');
        heading.scope = 'col';
        heading.textContent = column.toString(16).toUpperCase();
        headingRow.appendChild(heading);
      }
      head.appendChild(headingRow);

      const body = document.createElement('tbody');
      for (let row = 0; row < 16; row += 1) {
        const tableRow = document.createElement('tr');
        const address = document.createElement('th');
        address.scope = 'row';
        address.textContent = (row * 16).toString(16).toUpperCase().padStart(2, '0');
        tableRow.appendChild(address);
        for (let column = 0; column < 16; column += 1) {
          const index = row * 16 + column;
          const cell = document.createElement('td');
          cell.id = `${kind}BufferByte${index}`;
          cell.textContent = '--';
          cell.title = `${label} byte ${index}: not captured`;
          tableRow.appendChild(cell);
        }
        body.appendChild(tableRow);
      }
      table.replaceChildren(head, body);
    }

    function resetBuffer(kind, status = 'Waiting for device…') {
      const buffer = state[`${kind}Buffer`];
      const label = kind.toUpperCase();
      buffer.clear();
      for (let index = 0; index < 256; index += 1) {
        const cell = $(`${kind}BufferByte${index}`);
        cell.textContent = '--';
        cell.title = `${label} byte ${index}: not captured`;
        cell.classList.remove('filled');
      }
      $(`${kind}BufferStatus`).textContent = status;
    }

    function updateBuffer(kind, message) {
      const [indexText, value] = message.split(':');
      const index = Number(indexText);
      if (!Number.isInteger(index) || index < 0 || index > 255 || !/^[0-9A-F]{2}$/.test(value || '')) return;
      const buffer = state[`${kind}Buffer`];
      buffer.set(index, value);
      const cell = $(`${kind}BufferByte${index}`);
      cell.textContent = value;
      cell.title = `${kind.toUpperCase()} byte ${index}: 0x${value}`;
      cell.classList.add('filled');
      const count = buffer.size;
      $(`${kind}BufferStatus`).textContent = count === 256 ? 'Capture complete · 256 bytes' : `${count} of 256 bytes received`;
    }

    function showMonitorView(view) {
      state.monitorView = view;
      ['console', 'tx', 'rx'].forEach(name => {
        const selected = name === view;
        $(`${name}View`).hidden = !selected;
        $(`${name}Tab`).setAttribute('aria-selected', String(selected));
        $(`${name}Tab`).tabIndex = selected ? 0 : -1;
      });
      $('clearButton').textContent = view === 'console' ? 'Clear output' : `Clear ${view.toUpperCase()} buffer`;
    }

    function clearCurrentView() {
      if (state.monitorView !== 'console') {
        resetBuffer(state.monitorView, `${state.monitorView.toUpperCase()} buffer cleared`);
        return;
      }
      $('console').innerHTML = '<span class="console-empty">Output cleared. Waiting for wire activity.</span>';
    }

    function formulaText() {
      const a = $('operandA').value || '—';
      const b = $('operandB').value || '—';
      if (state.operation === 'abs') return `abs(${a})`;
      if (state.operation === 'neg') return `−(${a})`;
      if (state.operation === 'slt') return `slt(${a})`;
      if (state.operation === 'nop') return `nop(${a})`;
      return `${a} ${symbols[state.operation]} ${b}`;
    }

    async function updatePreview() {
      $('formula').textContent = formulaText();
      const result = await window.pywebview.api.preview_operation(
        state.operation, $('operandA').value, $('operandB').value, $('accumulator').checked ? 1 : 0
      );
      $('readoutTitle').textContent = `${state.operation.toUpperCase()} · ${binary.has(state.operation) ? 'BINARY' : 'UNARY'}`;
      if (result.ok) {
        $('wireBytes').textContent = result.uartHex;
        $('spiWireBytes').textContent = result.spiHex;
        $('frameLength').textContent = `UART ${result.uartLength}B · SPI ${result.spiLength}B · TAG ${result.tag}`;
        $('operandA').removeAttribute('aria-invalid');
        $('operandB').removeAttribute('aria-invalid');
      } else {
        $('wireBytes').textContent = result.error;
        $('spiWireBytes').textContent = '—';
        $('frameLength').textContent = 'INVALID';
        $('operandA').setAttribute('aria-invalid', 'true');
        if (binary.has(state.operation)) $('operandB').setAttribute('aria-invalid', 'true');
      }
    }

    function schedulePreview() {
      clearTimeout(state.previewTimer);
      state.previewTimer = setTimeout(updatePreview, 90);
    }

    async function refreshPorts() {
      const select = $('portSelect');
      const previous = select.value;
      const result = await window.pywebview.api.list_ports();
      if (!result.ok) { showError(result.error); return; }
      select.replaceChildren();
      if (!result.ports.length) {
        select.add(new Option('No serial ports found', ''));
      } else {
        result.ports.forEach(port => select.add(new Option(`${port.device} — ${port.description}`, port.device)));
        const preferred = previous || result.initialPort;
        if ([...select.options].some(option => option.value === preferred)) select.value = preferred;
      }
    }

    async function toggleConnection() {
      const button = $('connectButton');
      button.disabled = true;
      try {
        if (state.connected) {
          await window.pywebview.api.disconnect();
          setConnection(false, 'Disconnected');
          return;
        }
        setConnection(false, 'Connecting…');
        const result = await window.pywebview.api.connect($('portSelect').value, $('baudSelect').value);
        if (!result.ok) {
          setConnection(false, 'Connection failed', true);
          showError(result.error);
          return;
        }
        setConnection(true, `${result.port} · ${result.baud} baud`);
      } finally { button.disabled = false; }
    }

    async function transmitOperation() {
      const button = $('sendButton');
      button.disabled = true;
      const original = button.textContent;
      button.textContent = 'Sending…';
      try {
        const result = await window.pywebview.api.send_operation(
          state.operation, $('operandA').value, $('operandB').value, $('accumulator').checked ? 1 : 0
        );
        if (!result.ok) showError(result.error);
        else {
          $('wireBytes').textContent = result.uartHex;
          $('spiWireBytes').textContent = result.spiHex;
          $('frameLength').textContent = `UART ${result.uartLength}B · SPI ${result.spiLength}B · TAG ${result.tag}`;
          button.textContent = 'Sent';
          setTimeout(() => { button.textContent = original; }, 500);
        }
      } finally {
        setTimeout(() => { button.disabled = false; }, 180);
      }
    }

    async function sendControl(command, button) {
      button.disabled = true;
      try {
        const result = await window.pywebview.api.send_control(command);
        if (!result.ok) showError(result.error);
        return result;
      } finally {
        const delay = ['view', 'transfer'].includes(command) ? 700 : 180;
        setTimeout(() => { button.disabled = !state.connected; }, delay);
      }
    }

    async function viewTxBuffer(button) {
      showMonitorView('tx');
      resetBuffer('tx');
      const result = await sendControl('view', button);
      if (!result || !result.ok) $('txBufferStatus').textContent = 'Capture request failed';
    }

    async function transferSpi(button) {
      showMonitorView('rx');
      resetBuffer('rx');
      const result = await sendControl('transfer', button);
      if (!result || !result.ok) $('rxBufferStatus').textContent = 'Transfer request failed';
    }

    async function queueRaw() {
      const result = await window.pywebview.api.send_raw($('rawBytes').value);
      if (!result.ok) showError(result.error);
      else $('rawBytes').value = '';
    }

    async function pollEvents() {
      const result = await window.pywebview.api.drain_events();
      if (result.ok) result.events.forEach(event => {
        if (event.kind === 'connection') {
          if (event.message === 'disconnected') setConnection(false, 'Disconnected');
          return;
        }
        if (event.kind === 'tx_buffer') {
          updateBuffer('tx', event.message);
          return;
        }
        if (event.kind === 'rx_buffer') {
          updateBuffer('rx', event.message);
          return;
        }
        appendConsole(event.kind, event.kind === 'rx' ? event.message.replace(/[\r\n]+$/, '') : event.message);
      });
    }

    function selectOperation(button) {
      state.operation = button.dataset.op;
      document.querySelectorAll('.op-key').forEach(key => key.setAttribute('aria-pressed', String(key === button)));
      const needsB = binary.has(state.operation);
      $('operandB').disabled = !needsB;
      $('operandBWrap').classList.toggle('disabled', !needsB);
      updatePreview();
    }

    window.addEventListener('pywebviewready', async () => {
      document.querySelectorAll('.op-key').forEach(button => button.addEventListener('click', () => selectOperation(button)));
      ['operandA', 'operandB'].forEach(id => $(id).addEventListener('input', schedulePreview));
      $('accumulator').addEventListener('change', updatePreview);
      $('refreshButton').addEventListener('click', refreshPorts);
      $('connectButton').addEventListener('click', toggleConnection);
      $('sendButton').addEventListener('click', transmitOperation);
      $('transferButton').addEventListener('click', event => transferSpi(event.currentTarget));
      $('viewBufferButton').addEventListener('click', event => viewTxBuffer(event.currentTarget));
      $('cancelButton').addEventListener('click', event => sendControl('cancel', event.currentTarget));
      $('queueButton').addEventListener('click', queueRaw);
      $('rawBytes').addEventListener('keydown', event => { if (event.key === 'Enter') queueRaw(); });
      $('consoleTab').addEventListener('click', () => showMonitorView('console'));
      $('txTab').addEventListener('click', () => showMonitorView('tx'));
      $('rxTab').addEventListener('click', () => showMonitorView('rx'));
      document.querySelector('.view-switch').addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        const views = ['console', 'tx', 'rx'];
        const direction = event.key === 'ArrowLeft' ? -1 : 1;
        const nextView = views[(views.indexOf(state.monitorView) + direction + views.length) % views.length];
        showMonitorView(nextView);
        $(`${nextView}Tab`).focus();
      });
      $('clearButton').addEventListener('click', clearCurrentView);
      buildBufferTable('tx');
      buildBufferTable('rx');
      await refreshPorts();
      await updatePreview();
      state.eventTimer = setInterval(pollEvents, 160);
    });
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="preselect a serial port, such as COM5")
    parser.add_argument("--debug", action="store_true", help="enable WebView debug tools")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import webview
    except ImportError:
        print(
            "pywebview is required. Install dependencies with:\n"
            "  python -m pip install pyserial pywebview"
        )
        return 2

    api = FpuApi(initial_port=args.port)
    webview.create_window(
        "FPU Bench Console",
        html=HTML,
        js_api=api,
        width=1180,
        height=790,
        min_size=(760, 620),
    )
    try:
        webview.start(debug=args.debug)
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
