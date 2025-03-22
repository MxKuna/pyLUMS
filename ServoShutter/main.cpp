#include "mbed.h"
#include "platform/mbed_thread.h"

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
        default: printf("Invalid servo command\n");
    }
}

// Function to process incoming serial data
void processSerialInput() {
    char buffer[32];  // Temporary buffer for incoming data
    memset(buffer, 0, sizeof(buffer));
    
    // Check if data is available
    if (serial.readable()) {
        size_t bytes_read = serial.read(buffer, sizeof(buffer) - 1);  // Read available data
        buffer[bytes_read] = '\0';  // Null-terminate for safety
        
        // Process each character in the buffer
        for (size_t i = 0; i < bytes_read; i++) {
            char c = buffer[i];
            
            if (c == '?') {
                // Ensure there's another character after '?'
                if (i + 1 < bytes_read) {
                    char nextChar = buffer[i + 1];
                    if (nextChar >= '1' && nextChar <= '4') {
                        int servo_index = nextChar - '1';
                        printf("%d: %u\n", servo_index + 1, servo_positions[servo_index]);
                        i++;  // Skip the nextChar as it's part of the query
                    } else {
                        printf("Invalid query\n");
                    }
                } else {
                    printf("Invalid query\n");
                }
            } else {
                // Handle servo commands
                handleServoCommand(c);
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

    while (true) {
        processSerialInput();  // Continuously process incoming serial data
        ThisThread::sleep_for(10ms);
    }
}
