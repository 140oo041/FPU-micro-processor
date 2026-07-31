#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "esp_attr.h"
#include "driver/spi_master.h"
#include "frame.c"
#include "esp_log.h"
static const char *TAG = "FPU";

#include "driver/uart.h"
#include "freertos/FreeRTOS.h"

#define MOSI_PIN 23
#define MISO_PIN 19
#define SCLK_PIN 18
#define CS_PIN 5

#define BUFFERSIZE 256


//the extra DMA buffer for testing out how DMA works. DMA doesn't actually do anything right now since async isn't set up.
DMA_ATTR static uint8_t transmit_buffer[BUFFERSIZE];
DMA_ATTR static uint8_t receive_buffer[BUFFERSIZE];


#define ESP_HOST VSPI_HOST
esp_err_t ESP_ERR;
spi_device_handle_t spi_handle;

void uart_init() {
    // Initialize UART
    const int uart_num = UART_NUM_0;
    const int baud_rate = 115200;
    const int uart_buffer_size = 1024;

    uart_config_t uart_config = {
        .baud_rate = baud_rate,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
    };
    ESP_ERROR_CHECK(uart_driver_install(uart_num, uart_buffer_size, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(uart_num, &uart_config));

    ESP_LOGI(TAG, "UART initialized.");
}




void setup() {

    uart_init();

    // SPI bus configuration
spi_bus_config_t buscfg = {
    .mosi_io_num = MOSI_PIN,
    .miso_io_num = MISO_PIN,
    .sclk_io_num = SCLK_PIN,
    .quadwp_io_num = -1,
    .quadhd_io_num = -1,
    .max_transfer_sz = BUFFERSIZE
};



spi_device_interface_config_t devcfg = {
    .command_bits = 0,
    .address_bits = 0,
    .dummy_bits = 0,
    .clock_speed_hz = 8000,
    .duty_cycle_pos = 128,      //50% duty cycle
    .mode = 0,
    .spics_io_num = CS_PIN,
    .queue_size = 3,
};


    ESP_ERR = spi_bus_initialize(ESP_HOST, &buscfg, SPI_DMA_CH_AUTO);
    assert(ESP_ERR == ESP_OK);
    ESP_ERR = spi_bus_add_device(ESP_HOST, &devcfg, &spi_handle);
    assert(ESP_ERR == ESP_OK);

}

esp_err_t spi_transfer(uint8_t *tx, uint8_t *rx, size_t len) {

    if(!tx || !rx || len > BUFFERSIZE) {
        return ESP_ERR_INVALID_ARG;
    }

    memcpy(transmit_buffer, tx, len);
    
    spi_transaction_t trans = {0};
    trans.length = len * 8;
    trans.tx_buffer = tx ? transmit_buffer : NULL;
    trans.rx_buffer = tx ? receive_buffer : NULL;

    esp_err_t result = spi_device_transmit(spi_handle, &trans);

    if(result == ESP_OK) {
        memcpy(rx,receive_buffer, len);
    }

    return result;
}


void app_main(void)
{
    setup();
    // uint8_t transmit_data[100];
    // uint8_t receive_data[sizeof(transmit_data)];
    ESP_LOGI(TAG, "App initialized.");

    uint8_t data[128];

    while(1) {
        ESP_LOGI(TAG, "Waiting for data...");
        int count = uart_read_bytes(
            UART_NUM_0,
            data,
            sizeof(data) - 1,
            pdMS_TO_TICKS(1000)
        );
        ESP_LOGI(TAG, "Received %d bytes", count);
        if (count > 0) {
            data[count] = '\0'; // Null-terminate the received data
            ESP_LOG_BUFFER_HEX_LEVEL(TAG, data, count, ESP_LOG_INFO);

            switch(data[0]) {
                case 'A':
                    fpu_add((uint16_t)((uint16_t)data[1] << 8 | data[2]), (uint16_t)((uint16_t)data[3] << 8 | data[4]), (data[5]));
                    break;
                case 'S':
                    fpu_sub((uint16_t)((uint16_t)data[1] << 8 | data[2]), (uint16_t)((uint16_t)data[3] << 8 | data[4]), (data[5]));
                    break;

                case 'M':
                    fpu_mul((uint16_t)((uint16_t)data[1] << 8 | data[2]), (uint16_t)((uint16_t)data[3] << 8 | data[4]), (data[5]));
                    break;

                case 'D':
                    fpu_div((uint16_t)((uint16_t)data[1] << 8 | data[2]), (uint16_t)((uint16_t)data[3] << 8 | data[4]), (data[5]));
                    break;

                case 'B':
                    fpu_abs((uint16_t)((uint16_t)data[1] << 8 | data[2]), (data[3]));
                    break;
                case 'N':
                    fpu_neg((uint16_t)((uint16_t)data[1] << 8 | data[2]), (data[3]));
                    break;

                case 'L':
                    fpu_slt((uint16_t)((uint16_t)data[1] << 8 | data[2]), (data[3]));
                    break;

                case 'O':
                    fpu_nop((uint16_t)((uint16_t)data[1] << 8 | data[2]), (data[3]));
                    break;

                case 'P':
                    for(int i = 1; i < count; i++) {
                        queue_byte(data[i]);
                    }
                    break;

                case 'R':
                    ESP_ERROR_CHECK(spi_transfer(transmit_buffer_data, receive_buffer_data,sizeof(transmit_buffer_data)));
                    for (size_t i = 0; i < sizeof(receive_buffer_data); i++) {
                        ESP_LOGI(TAG, "RX[%u] = 0x%02X", (unsigned)i, receive_buffer_data[i]);
                    }
                    break;
                case 'X':
                    ESP_LOGI(TAG, "Exiting...");
                    break;
                case 'V':
                    for(int i = 0; i < BUFFERSIZE; i++) {
                        ESP_LOGI(TAG, "TX[%u] = 0x%02X", (unsigned)((transmit_idx_lower + i) % BUFFERSIZE), transmit_buffer_data[(transmit_idx_lower + i) % BUFFERSIZE]);
                    }
                    break;
                default:
                    ESP_LOGI(TAG, "Unknown command: %s", data);
                    break;
            }

        }
    }

    
}

// typedef enum op_type = {ADD,SUB,MUL,DIV,}
