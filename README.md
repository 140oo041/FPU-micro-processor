# FPU Bench Console

This project combines ESP32 firmware with a Windows desktop WebView for composing FPU operations, sending them over UART, transferring the queued frame over SPI, and inspecting the transmit and receive buffers.

## Requirements

- An ESP32 development board
- An FPU connected to the ESP32 SPI pins
- ESP-IDF 5.x with the `esp32` target installed
- Python 3.9 or newer
- A data-capable USB cable and the appropriate USB-to-UART driver
- Microsoft Edge WebView2 Runtime (included with current Windows installations)

The firmware uses these connections:

| Signal | ESP32 GPIO |
| --- | ---: |
| MOSI | 23 |
| MISO | 19 |
| SCLK | 18 |
| CS | 5 |
| UART | UART0 over the board's USB serial connection |

UART is configured for 115200 baud, 8 data bits, no parity, and one stop bit.

## Install the desktop application

From PowerShell or Command Prompt in the project directory, create a virtual environment and install the two Python dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install pyserial pywebview
```

If `.venv` already exists, activate it and run only the final installation command.

## Build and flash the firmware

Open an ESP-IDF terminal in the project directory, then run:

```powershell
idf.py set-target esp32
idf.py build
idf.py -p COM5 flash
```

Replace `COM5` with the ESP32's serial port. You can briefly verify startup with:

```powershell
idf.py -p COM5 monitor
```

Exit the monitor before opening the desktop application. Only one program can own the serial port at a time.

## Start the WebView

With the Python virtual environment active, run:

```powershell
python pc_interface.py --port COM5
```

The `--port` argument is optional; the port can also be selected in the application. Use `--debug` to enable the WebView developer tools:

```powershell
python pc_interface.py --port COM5 --debug
```

## Normal operation

1. Select the ESP32 serial port and leave the baud rate at **115200**.
2. Select **Connect**. The connection controls lock while the port is open.
3. Choose an operation and enter its operand values.
4. Enable **Accumulator** when the operation should use the accumulator bit.
5. Inspect both protocol rows in the top readout:
   - **UART TX** is the command sent from the PC to the ESP32.
   - **SPI FRAME** is the locally derived frame expected to be queued for the FPU.
6. Select **Send operation** to transmit the UART command and queue the SPI frame in firmware.
7. Select **View TX buffer** to request the firmware's actual transmit buffer. The application switches to the indexed TX-buffer view automatically.
8. Select **SPI transfer** to send the buffer to the FPU. The application clears and opens the RX-buffer view while the returned bytes arrive.
9. Use the **Console**, **TX buffer**, and **RX buffer** tabs to move between normal firmware output and the two 256-byte buffer views.

The clear button applies only to the currently selected inspection view.

## Frame formats

Binary operations (`ADD`, `SUB`, `MUL`, and `DIV`) use these layouts:

```text
UART: [command] [operand A: 2 bytes] [operand B: 2 bytes] [accumulator]
SPI:  [header]  [operand A: 2 bytes] [operand B: 2 bytes] [CRC]
```

Unary operations (`ABS`, `NEG`, `SLT`, and `NOP`) use:

```text
UART: [command] [operand A: 2 bytes] [accumulator]
SPI:  [header]  [operand A: 2 bytes] [CRC]
```

Operands are the upper 16 bits of an IEEE-754 single-precision value (bfloat16 representation). The SPI header contains the opcode, accumulator flag, binary/unary flag, and three-bit tag.

For example, `ADD 1.0, 2.0` with accumulator disabled and tag zero displays:

```text
UART TX:   41 3F 80 40 00 00
SPI FRAME: 08 3F 80 40 00 34
```

`0x41` is the ASCII `A` UART command. Firmware consumes it and constructs the `0x08` SPI header. `0x34` is the CRC-8/AUTOSAR value calculated over the preceding five SPI bytes.

## Raw queue and control actions

- **Raw queue bytes** accepts space- or comma-separated decimal, hexadecimal, or binary values. The application prefixes the firmware's `P` command.
- **View TX buffer** sends `V` and captures the firmware's `TX[index]` output in the TX-buffer view.
- **SPI transfer** sends `R` and captures `RX[index]` output in the RX-buffer view.
- **Cancel** sends `X`. The current firmware logs `Exiting...` but does not terminate its main loop.

## Troubleshooting

### No serial ports appear

- Confirm that the USB cable supports data.
- Install the board's USB-to-UART driver.
- Select **Refresh** after connecting the board.
- Close ESP-IDF Monitor, another terminal, or any program already using the COM port.

### Connection fails or immediately disconnects

- Verify the selected COM port in Windows Device Manager.
- Ensure no other application owns the port.
- Reconnect the board and refresh the port list.

### Commands take approximately ten seconds

The current firmware requests up to 127 bytes in `uart_read_bytes()` with a ten-second timeout. A four- or six-byte command can therefore remain blocked until that timeout expires. The UART parser should instead read the command byte first and then request the exact remaining frame length.

### UART bytes look correct but operands are corrupted

When rebuilding a 16-bit operand from two UART bytes, the first byte must be shifted left:

```c
uint16_t operand = ((uint16_t)data[1] << 8) | data[2];
```

Casting to `uint16_t` without changing `>> 8` to `<< 8` still discards the high byte.

### The expected SPI row differs from the TX buffer

The top SPI row is derived locally from the selected operation and predicted tag. The TX-buffer tab shows what the firmware actually queued and is the authoritative view for debugging firmware behavior.

### SPI data is missing or incorrect

- Verify MOSI, MISO, SCLK, CS, power, and ground connections.
- Confirm that the FPU uses SPI mode 0.
- Inspect the TX buffer before transferring and the RX buffer afterward.
- Remember that the firmware currently transfers the complete 256-byte buffer.
