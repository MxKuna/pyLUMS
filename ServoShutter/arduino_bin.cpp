#include <Servo.h>

// Servo objects
Servo servo1;
Servo servo2;
Servo servo3;
Servo servo4;

// Pin definitions for STM32 Nucleo L432KC using correct Arduino pin numbering
const int SERVO1_PIN = 9;  // PA_8 -> D9
const int SERVO2_PIN = 1;  // PA_9 -> D1
const int SERVO3_PIN = 0;  // PA_10 -> D0
const int SERVO4_PIN = 10; // PA_11 -> D10

// Servo pulsewidth constants (same as original)
const uint32_t PULSEWIDTH_LOW = 1100;
const uint32_t PULSEWIDTH_MID = 1400;
const uint32_t PULSEWIDTH_HIGH = 1700;

// Binary Protocol Command Codes
const uint8_t CMD_SET_POSITION = 0x01;
const uint8_t CMD_QUERY_POSITION = 0x02;
const uint8_t CMD_HANDSHAKE = 0x03;  // New handshake command

// Position Value Codes
const uint8_t POS_LOW = 0x01;
const uint8_t POS_MID = 0x02;
const uint8_t POS_HIGH = 0x03;

// Response codes
const uint8_t RESP_SUCCESS = 0x00;
const uint8_t RESP_ERROR = 0xFF;
const uint8_t RESP_INIT_COMPLETE = 0xAA;
const uint8_t RESP_HANDSHAKE = 0xBB;  // Handshake response

// Servo positions (for queries)
uint32_t servo_positions[4] = {PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH, PULSEWIDTH_HIGH};

// Helper function to set servo positions
void setServoPosition(uint8_t servo_index, uint8_t position) {
  uint32_t pulsewidth;
  
  // Map position value to pulsewidth
  switch(position) {
    case POS_LOW:
      pulsewidth = PULSEWIDTH_LOW;
      break;
    case POS_MID:
      pulsewidth = PULSEWIDTH_MID;
      break;
    case POS_HIGH:
      pulsewidth = PULSEWIDTH_HIGH;
      break;
    default:
      Serial.write(RESP_ERROR); // Error code
      return;
  }
  
  // Set servo position based on servo index
  if (servo_index >= 0 && servo_index <= 3) {
    switch(servo_index) {
      case 0:
        servo1.writeMicroseconds(pulsewidth);
        break;
      case 1:
        servo2.writeMicroseconds(pulsewidth);
        break;
      case 2:
        servo3.writeMicroseconds(pulsewidth);
        break;
      case 3:
        servo4.writeMicroseconds(pulsewidth);
        break;
    }
    servo_positions[servo_index] = pulsewidth;
    
    // Send confirmation (RESP_SUCCESS = success)
    Serial.write(RESP_SUCCESS);
  } else {
    // Invalid servo index
    Serial.write(RESP_ERROR);
  }
}

// Function to handle position query
void queryServoPosition(uint8_t servo_index) {
  if (servo_index >= 0 && servo_index <= 3) {
    // Response format:
    // Byte 0: RESP_SUCCESS (success)
    // Byte 1: Servo index (0-3)
    // Bytes 2-5: Position value (uint32_t, 4 bytes, MSB first)
    
    Serial.write(RESP_SUCCESS); // Success code
    Serial.write(servo_index);
    
    // Send position as 4 bytes (MSB first)
    Serial.write((servo_positions[servo_index] >> 24) & 0xFF);
    Serial.write((servo_positions[servo_index] >> 16) & 0xFF);
    Serial.write((servo_positions[servo_index] >> 8) & 0xFF);
    Serial.write(servo_positions[servo_index] & 0xFF);
  } else {
    Serial.write(RESP_ERROR); // Error code
  }
}

// Function to handle handshake request
void handleHandshake() {
  Serial.write(RESP_HANDSHAKE);
}

// Function to process incoming serial data
void processSerialInput() {
  // Check if enough data is available
  if (Serial.available() > 0) {
    uint8_t cmd = Serial.read();
    
    switch(cmd) {
      case CMD_SET_POSITION:
        // Need two more bytes for servo index and position
        while (Serial.available() < 2) {
          delay(5); // Short delay to wait for data
        }
        if (Serial.available() >= 2) {
          uint8_t servo_index = Serial.read();
          uint8_t position = Serial.read();
          setServoPosition(servo_index, position);
        } else {
          // Not enough data, send error
          Serial.write(RESP_ERROR);
        }
        break;
        
      case CMD_QUERY_POSITION:
        // Need one more byte for servo index
        while (Serial.available() < 1) {
          delay(5); // Short delay to wait for data
        }
        if (Serial.available() >= 1) {
          uint8_t servo_index = Serial.read();
          queryServoPosition(servo_index);
        } else {
          // Not enough data, send error
          Serial.write(RESP_ERROR);
        }
        break;
        
      case CMD_HANDSHAKE:
        handleHandshake();
        break;
        
      default:
        // Unknown command
        Serial.write(RESP_ERROR);
        break;
    }
  }
}

void setup() {
  // Initialize serial communication
  Serial.begin(115200);
  
  // Wait for serial to be ready
  delay(100);
  
  // Attach servos to pins
  servo1.attach(SERVO1_PIN);
  servo2.attach(SERVO2_PIN);
  servo3.attach(SERVO3_PIN);
  servo4.attach(SERVO4_PIN);

  analogWriteFrequency(SERVO1_PIN, 50)
  
  // Reset to initial positions (all HIGH)
  setServoPosition(0, POS_HIGH);
  setServoPosition(1, POS_HIGH);
  setServoPosition(2, POS_HIGH);
  setServoPosition(3, POS_HIGH);
  
  // Send initialization complete signal
  Serial.write(RESP_INIT_COMPLETE);
  Serial.flush();
}

void loop() {
  processSerialInput();  // Continuously process incoming serial data
  delay(10);  // Similar to the original Mbed sleep
}