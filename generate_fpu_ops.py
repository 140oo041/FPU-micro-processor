#!/usr/bin/env python3
"""Generate random FPU operations for the sample project's frame format."""

import argparse
import json
import random
import struct
import sys


OPERATIONS = {
    "add": {"opcode": 0b000, "binary": True},
    "sub": {"opcode": 0b001, "binary": True},
    "mul": {"opcode": 0b010, "binary": True},
    "div": {"opcode": 0b011, "binary": True},
    "neg": {"opcode": 0b100, "binary": False},
    "abs": {"opcode": 0b101, "binary": False},
    "slt": {"opcode": 0b110, "binary": False},
    "nop": {"opcode": 0b111, "binary": False},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("count", type=int, help="number of operations to generate")
    parser.add_argument("--seed", type=int, help="seed for repeatable output")
    parser.add_argument(
        "--format",
        choices=("c", "hex", "json"),
        default="c",
        help="output format (default: c)",
    )
    parser.add_argument("--minimum", type=float, default=-100.0)
    parser.add_argument("--maximum", type=float, default=100.0)
    return parser.parse_args()


def random_nonzero(rng: random.Random, minimum: float, maximum: float) -> float:
    value = rng.uniform(minimum, maximum)
    while abs(value) < 0.001:
        value = rng.uniform(minimum, maximum)
    return value


def c_float(value: float) -> str:
    text = format(value, ".8g")
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text + "f"


def bfloat16_bytes(value: float) -> bytes:
    """Match frame.c: keep the upper 16 bits of an IEEE-754 float."""
    return struct.pack(">f", value)[:2]


def generate_operations(args: argparse.Namespace) -> list[dict]:
    if args.count < 0:
        raise ValueError("count must be non-negative")
    if args.minimum >= args.maximum:
        raise ValueError("minimum must be less than maximum")

    rng = random.Random(args.seed)
    names = tuple(OPERATIONS)
    generated = []

    for index in range(args.count):
        name = rng.choice(names)
        definition = OPERATIONS[name]
        operands = [rng.uniform(args.minimum, args.maximum)]

        if definition["binary"]:
            if name == "div":
                operands.append(random_nonzero(rng, args.minimum, args.maximum))
            else:
                operands.append(rng.uniform(args.minimum, args.maximum))

        generated.append(
            {
                "operation": name,
                "opcode": definition["opcode"],
                "binary": definition["binary"],
                "acc": rng.randint(0, 1),
                "tag": index % 8,
                "operands": operands,
            }
        )

    return generated


def encode(operation: dict) -> bytes:
    header = (
        (operation["opcode"] << 5)
        | (operation["acc"] << 4)
        | (int(operation["binary"]) << 3)
        | operation["tag"]
    )
    frame = bytearray([header])
    for operand in operation["operands"]:
        frame.extend(bfloat16_bytes(operand))
    return bytes(frame)


def print_operations(operations: list[dict], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(operations, indent=2))
        return

    for operation in operations:
        if output_format == "hex":
            print(encode(operation).hex(" ").upper())
            continue

        arguments = [c_float(value) for value in operation["operands"]]
        arguments.append(str(operation["acc"]))
        print(f"fpu_{operation['operation']}({', '.join(arguments)});")


def main() -> int:
    args = parse_args()
    try:
        operations = generate_operations(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print_operations(operations, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
