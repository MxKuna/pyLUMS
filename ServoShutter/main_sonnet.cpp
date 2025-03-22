#include "mbed.h"
#include "platform/mbed_thread.h"
#include <string>

// Servos
PwmOut servo1(PA_8);
PwmOut servo2(PA_9);
PwmOut servo3(PA_10);
PwmOut servo4(PA_11);

// Serial
BufferedSerial serial(USBTX, USBRX, 115200);  // BufferedSerial for robust handling

// Servo pulsewidth constants
const uint32_t PULSEWIDTH_LOW = 1100;
const uint32_t PULSEWIDTH_MID = 1400;
const uint32_t PULSEWIDTH_HIGH = 1700;

// Servo positions (for queries)
uint32_t servo_positions[4] = {PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH};

// Command buffer for reliable processing
char cmd_buffer[128];
size_t cmd_pos = 0;

// Helper function to set servo positions
void handleServoCommand(char cmd) {
    switch(cmd) {
        case 'q': servo1.pulsewidth_us(PULSEWIDTH_LOW); servo_positions[0] = PULSEWIDTH_LOW; break;
        case 'a': servo1.pulsewidth_us(PULSEWIDTH_MID); servo_positions[0] = PULSEWIDTH_MID; break;
        case 'z': servo1.pulsewidth_us(PULSEWIDTH_HIGH); servo_positions[0] = PULSEWIDTH_HIGH; break;
        case 'w': servo2.pulsewidth_us(PULSEWIDTH_LOW); servo_positions[1] = PULSEWIDTH_LOW; break;
        case 's': servo2.pulsewidth_us(PULSEWIDTH_MID); servo_positions[1] = PULSEWIDTH_MID; break;
        case 'x': servo2.pulsewidth_us(PULSEWIDTH_HIGH); servo_positions[1] = PULSEWIDTH_HIGH; break;
        case 'e': servo3.pulsewidth_us(PULSEWIDTH_LOW); servo_positions[2] = PULSEWIDTH_LOW; break;
        case 'd': servo3.pulsewidth_us(PULSEWIDTH_MID); servo_positions[2] = PULSEWIDTH_MID; break;
        case 'c': servo3.pulsewidth_us(PULSEWIDTH_HIGH); servo_positions[2] = PULSEWIDTH_HIGH; break;
        case 'r': servo4.pulsewidth_us(PULSEWIDTH_LOW); servo_positions[3] = PULSEWIDTH_LOW; break;
        case 'f': servo4.pulsewidth_us(PULSEWIDTH_MID); servo_positions[3] = PULSEWIDTH_MID; break;
        case 'v': servo4.pulsewidth_us(PULSEWIDTH_HIGH); servo_positions[3] = PULSEWIDTH_HIGH; break;
        default: printf("Invalid servo command: %c\n", cmd);
    }
}

// Function to send query responses with proper formatting
void sendQueryResponse(int servo_index) {
    char response[32];
    sprintf(response, "%d: %u\r\n", servo_index + 1, servo_positions[servo_index]);
    serial.write(response, strlen(response));
}

// Process a complete command
void processCommand(const char* cmd) {
    // Check if it's a query
    if (cmd[0] == '?' && cmd[1] >= '1' && cmd[1] <= '4') {
        int servo_index = cmd[1] - '1';
        sendQueryResponse(servo_index);
    } 
    // Check if it's a servo movement command
    else if (strchr("qazwsxedcrfv", cmd[0]) != NULL) {
        handleServoCommand(cmd[0]);
    }
    else {
        printf("Unknown command: %s\n", cmd);
    }
}

// Function to read and process serial data
void processSerialInput() {
    char buffer[32];
    memset(buffer, 0, sizeof(buffer));
    
    if (serial.readable()) {
        size_t bytes_read = serial.read(buffer, sizeof(buffer) - 1);
        buffer[bytes_read] = '\0';
        
        // Process each character
        for (size_t i = 0; i < bytes_read; i++) {
            char c = buffer[i];
            
            if (c == '\r' || c == '\n') {
                // End of command - process if we have content
                if (cmd_pos > 0) {
                    cmd_buffer[cmd_pos] = '\0';
                    processCommand(cmd_buffer);
                    cmd_pos = 0;  // Reset buffer
                }
            } 
            else if (cmd_pos < sizeof(cmd_buffer) - 1) {
                // Add to command buffer
                cmd_buffer[cmd_pos++] = c;
            }
        }
    }
}

int main() {
    // Initialize servos
    servo1.period(0.020);
    servo2.period(0.020);
    servo3.period(0.020);
    servo4.period(0.020);

    printf("Initializing servos...\n");

    // Reset to initial positions
    handleServoCommand('z');
    handleServoCommand('x');
    handleServoCommand('c');
    handleServoCommand('v');

    // Reset command buffer
    cmd_pos = 0;
    memset(cmd_buffer, 0, sizeof(cmd_buffer));

    while (true) {
        processSerialInput();  // Process incoming serial data
        ThisThread::sleep_for(5ms);  // Short sleep to prevent CPU hogging
    }
}
