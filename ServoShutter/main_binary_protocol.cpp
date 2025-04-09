#include "mbed.h"
#include "platform/mbed_thread.h"

// Servos
PwmOut servo1(PA_8);
PwmOut servo2(PA_9);
PwmOut servo3(PA_10);
PwmOut servo4(PA_11);

// Serial
BufferedSerial serial(USBTX, USBRX, 115200);  // BufferedSerial for robust handling

// Protocol constants
const uint8_t CMD_START = 0xFF;
const uint8_t CMD_END = 0xFE;
const uint8_t CMD_MOVE = 0x01;
const uint8_t CMD_QUERY = 0x02;
const uint8_t RESP_STATUS_OK = 0x00;
const uint8_t RESP_STATUS_ERROR = 0x01;

// Servo pulsewidth constants
const uint32_t PULSEWIDTH_LOW = 1100;
const uint32_t PULSEWIDTH_MID = 1400;
const uint32_t PULSEWIDTH_HIGH = 1700;

// Servo positions (for queries)
uint32_t servo_positions[4] = {PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH};

// Move servo to specified position
void moveServo(uint8_t servo, uint8_t position) {
    if (servo > 3) {
        return; // Invalid servo number
    }
    
    uint32_t pulsewidth;
    switch (position) {
        case 0: pulsewidth = PULSEWIDTH_LOW; break;
        case 1: pulsewidth = PULSEWIDTH_MID; break;
        case 2: pulsewidth = PULSEWIDTH_HIGH; break;
        default: return; // Invalid position
    }
    
    // Update servo position
    switch (servo) {
        case 0: servo1.pulsewidth_us(pulsewidth); break;
        case 1: servo2.pulsewidth_us(pulsewidth); break;
        case 2: servo3.pulsewidth_us(pulsewidth); break;
        case 3: servo4.pulsewidth_us(pulsewidth); break;
    }
    
    // Store position for later queries
    servo_positions[servo] = pulsewidth;
}

// Send servo position back via serial
void sendServoPosition(uint8_t servo) {
    if (servo > 3) {
        // Send error response
        uint8_t resp[] = {CMD_START, RESP_STATUS_ERROR, 0x00, 0x00, CMD_END};
        serial.write(resp, sizeof(resp));
        return;
    }
    
    // Get current position
    uint32_t position = servo_positions[servo];
    
    // Create response: START + STATUS + SERVO_ID + POSITION_HI + POSITION_LO + END
    uint8_t resp[6];
    resp[0] = CMD_START;
    resp[1] = RESP_STATUS_OK;
    resp[2] = servo;
    resp[3] = (position >> 8) & 0xFF;  // High byte
    resp[4] = position & 0xFF;         // Low byte
    resp[5] = CMD_END;
    
    serial.write(resp, sizeof(resp));
}

// Process a complete command
void processCommand(uint8_t* cmd, size_t len) {
    if (len < 2) return; // Need at least command and parameter
    
    uint8_t cmdType = cmd[0];
    uint8_t param = cmd[1];
    
    switch (cmdType) {
        case CMD_MOVE: {
            uint8_t servo = (param >> 4) & 0x0F;   // Upper 4 bits = servo number (0-3)
            uint8_t position = param & 0x0F;       // Lower 4 bits = position (0-2)
            moveServo(servo, position);
            break;
        }
        case CMD_QUERY: {
            uint8_t servo = param & 0x0F;
            sendServoPosition(servo);
            break;
        }
    }
}

// Process incoming serial data with improved buffering
void processSerialInput() {
    static uint8_t cmdBuffer[16];       // Command buffer
    static size_t bufferPos = 0;
    static bool inCommand = false;
    
    uint8_t byte;
    
    // Process all available bytes
    while (serial.readable()) {
        serial.read(&byte, 1);
        
        // Command start marker
        if (byte == CMD_START) {
            bufferPos = 0;
            inCommand = true;
            continue;
        }
        
        // Command end marker
        if (byte == CMD_END && inCommand) {
            processCommand(cmdBuffer, bufferPos);
            inCommand = false;
            continue;
        }
        
        // Add byte to buffer if in command mode
        if (inCommand && bufferPos < sizeof(cmdBuffer)) {
            cmdBuffer[bufferPos++] = byte;
        }
    }
}

// For backward compatibility
void handleLegacyCommand(char cmd) {
    // Convert legacy character commands to new format
    uint8_t servo, position;
    
    switch(cmd) {
        // Servo 1
        case 'q': servo = 0; position = 0; break;
        case 'a': servo = 0; position = 1; break;
        case 'z': servo = 0; position = 2; break;
        // Servo 2
        case 'w': servo = 1; position = 0; break;
        case 's': servo = 1; position = 1; break;
        case 'x': servo = 1; position = 2; break;
        // Servo 3
        case 'e': servo = 2; position = 0; break;
        case 'd': servo = 2; position = 1; break;
        case 'c': servo = 2; position = 2; break;
        // Servo 4
        case 'r': servo = 3; position = 0; break;
        case 'f': servo = 3; position = 1; break;
        case 'v': servo = 3; position = 2; break;
        default: return; // Invalid command
    }
    
    moveServo(servo, position);
}

// Process legacy ASCII commands for backward compatibility
void processLegacyInput() {
    static char buffer[32];
    static size_t bufferPos = 0;
    
    // Check if data is available
    if (serial.readable()) {
        // Read available data
        size_t bytes_read = serial.read(buffer + bufferPos, sizeof(buffer) - bufferPos - 1);
        bufferPos += bytes_read;
        buffer[bufferPos] = '\0';  // Null-terminate for safety
        
        // Process buffer contents
        size_t i = 0;
        while (i < bufferPos) {
            char c = buffer[i++];
            
            if (c == '?') {
                // Legacy query format
                if (i < bufferPos) {
                    char nextChar = buffer[i++];
                    if (nextChar >= '1' && nextChar <= '4') {
                        uint8_t servo = nextChar - '1';
                        printf("%d: %u\n", servo + 1, servo_positions[servo]);
                    } else {
                        printf("Invalid query\n");
                    }
                } else {
                    // Incomplete query, move remaining data to buffer start
                    buffer[0] = '?';
                    bufferPos = 1;
                    break;
                }
            } else {
                // Handle legacy servo commands
                handleLegacyCommand(c);
            }
        }
        
        // Reset buffer position after processing
        bufferPos = 0;
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
    moveServo(0, 2); // Servo 1, high position
    moveServo(1, 2); // Servo 2, high position
    moveServo(2, 2); // Servo 3, high position 
    moveServo(3, 2); // Servo 4, high position

    // Main loop
    while (true) {
        processSerialInput();   // Process new binary protocol
        processLegacyInput();   // For backward compatibility
        ThisThread::sleep_for(5ms);
    }
}