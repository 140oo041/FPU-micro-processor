#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <string.h>

#define ADD 0b000
#define SUB 0b001
#define MUL 0b010
#define DIV 0b011
#define NEG 0b100
#define ABS 0b101
#define SLT 0b110
#define NOP 0b111

#define DATA_BUFFERSIZE 256

static uint8_t tag = 0;
uint8_t transmit_buffer_data[DATA_BUFFERSIZE];
uint8_t transmit_idx_lower;
uint8_t transmit_idx_higher;
uint8_t receive_buffer_data[DATA_BUFFERSIZE];
uint8_t receive_idx_lower;
uint8_t receive_idx_higher;

uint8_t binary_op(uint8_t opcode, uint8_t acc) {
    uint8_t out = ((opcode & 0x07)<<5) | ((acc&0x01)<<4) | (1<<3) | (tag);
    tag = (tag+1)%8;
    return out;
}

uint8_t unary_op(uint8_t opcode, uint8_t acc) {
    uint8_t out = ((opcode & 0x07)<<5) | ((acc&0x01)<<4) | (0<<3) | (tag);
    tag = (tag+1)%8;
    return out;
}

void queue_byte(uint8_t byte) {
    assert((transmit_idx_higher + 1)%DATA_BUFFERSIZE != transmit_idx_lower);
    transmit_buffer_data[(transmit_idx_higher)%DATA_BUFFERSIZE] = byte;
    transmit_idx_higher = (transmit_idx_higher + 1) % DATA_BUFFERSIZE;
}

uint8_t crc8_autosar(const uint8_t *bytes, size_t length) {
    uint8_t crc = 0xFF;

    for (size_t byte_index = 0; byte_index < length; byte_index++) {
        crc ^= bytes[byte_index];

        for (uint8_t bit = 0; bit < 8; bit++) {
            if ((crc & 0x80) != 0) {
                crc = (uint8_t)((crc << 1) ^ 0x2F);
            } else {
                crc = (uint8_t)(crc << 1);
            }
        }
    }

    return (uint8_t)(crc ^ 0xFF);
}

uint8_t read_byte() {
    assert(receive_idx_lower != receive_idx_higher);
    uint8_t byte = receive_buffer_data[receive_idx_lower];
    receive_idx_lower = (receive_idx_lower + 1) % DATA_BUFFERSIZE;
    return byte;
}

void fpu_add(uint16_t op1, uint16_t op2, uint8_t acc) {
    uint8_t frame[] = {
        binary_op(ADD, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF),
        (uint8_t)(op2 >> 8),
        (uint8_t)(op2 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}

void fpu_sub(uint16_t op1, uint16_t op2, uint8_t acc) {
    uint8_t frame[] = {
        binary_op(SUB, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF),
        (uint8_t)(op2 >> 8),
        (uint8_t)(op2 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}
void fpu_mul(uint16_t op1, uint16_t op2, uint8_t acc) {
    uint8_t frame[] = {
        binary_op(MUL, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF),
        (uint8_t)(op2 >> 8),
        (uint8_t)(op2 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}
void fpu_div(uint16_t op1, uint16_t op2, uint8_t acc) {
    uint8_t frame[] = {
        binary_op(DIV, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF),
        (uint8_t)(op2 >> 8),
        (uint8_t)(op2 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}
void fpu_abs(uint16_t op1, uint8_t acc) {
    uint8_t frame[] = {
        unary_op(ABS, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}

void fpu_slt(uint16_t op1, uint8_t acc) {
    uint8_t frame[] = {
        unary_op(SLT, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}

void fpu_neg(uint16_t op1, uint8_t acc) {
    uint8_t frame[] = {
        unary_op(NEG, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}

void fpu_nop(uint16_t op1, uint8_t acc) {
    uint8_t frame[] = {
        unary_op(NOP, acc),
        (uint8_t)(op1 >> 8),
        (uint8_t)(op1 & 0xFF)
    };
    for (size_t i = 0; i < sizeof(frame); i++) {
        queue_byte(frame[i]);
    }
    queue_byte(crc8_autosar(frame, sizeof(frame)));
}

uint16_t float_to_bytes(float f) {
    uint32_t f_bits;
    // Copy the raw 32 bits of the float safely into an integer type
    memcpy(&f_bits, &f, sizeof(f));
    
    // Shift out the lower 16 bits of the mantissa to keep the upper 16 bits
    // This yields: 1 sign bit, 8 exponent bits, and the 7 highest mantissa bits
    return (uint16_t)(f_bits >> 16);
}

float bytes_to_float(uint16_t b) {
    uint32_t f_bits = ((uint32_t)b) << 16; // Shift the 16 bits back to the upper half
    float f;
    memcpy(&f, &f_bits, sizeof(f)); // Copy the bits back into a float
    return f;
}

void fpu_add_f(float op1, float op2, uint8_t acc) {
    fpu_add(float_to_bytes(op1), float_to_bytes(op2), acc);
}

void fpu_sub_f(float op1, float op2, uint8_t acc) {
    fpu_sub(float_to_bytes(op1), float_to_bytes(op2), acc);
}

void fpu_mul_f(float op1, float op2, uint8_t acc) {
    fpu_mul(float_to_bytes(op1), float_to_bytes(op2), acc);
}

void fpu_div_f(float op1, float op2, uint8_t acc) {
    fpu_div(float_to_bytes(op1), float_to_bytes(op2), acc);
}

void fpu_abs_f(float op1, uint8_t acc) {
    fpu_abs(float_to_bytes(op1), acc);
}

void fpu_slt_f(float op1, uint8_t acc) {
    fpu_slt(float_to_bytes(op1), acc);
}

void fpu_neg_f(float op1, uint8_t acc) {
    fpu_neg(float_to_bytes(op1), acc);
}

void fpu_nop_f(float op1, uint8_t acc) {
    fpu_nop(float_to_bytes(op1), acc);
}
