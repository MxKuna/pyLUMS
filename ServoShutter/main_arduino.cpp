// Servo pins
#include <Servo.h>

Servo servo1;
Servo servo2;
Servo servo3;
Servo servo4;

// Servo positions (for queries)
int servo_positions[4] = {2000, 2000, 2000, 2000}; // Store positions in degrees or microseconds

void setup() {
  // Initialize serial
  Serial.begin(115200);
  
  // Attach servos to pins
  servo1.attach(9);  // Change to your Arduino pins
  servo2.attach(10);
  servo3.attach(11);
  servo4.attach(12);
  
  // Set initial positions
  handleServoCommand('z');
  handleServoCommand('x');
  handleServoCommand('c');
  handleServoCommand('v');
  
  Serial.println("Initializing servos...");
}

void loop() {
  processSerialInput();
  delay(10);
}

// Helper function to set servo positions
void handleServoCommand(char cmd) {
  switch(cmd) {
    case 'q': servo1.writeMicroseconds(1100); servo_positions[0] = 1100; break;
    case 'a': servo1.writeMicroseconds(1400); servo_positions[0] = 1400; break;
    case 'z': servo1.writeMicroseconds(1700); servo_positions[0] = 1700; break;
    // Repeat for other servos...
  }
}

void processSerialInput() {
  if (Serial.available() > 0) {
    char c = Serial.read();
    
    if (c == '?') {
      if (Serial.available() > 0) {
        char nextChar = Serial.read();
        if (nextChar >= '1' && nextChar <= '4') {
          int servo_index = nextChar - '1';
          Serial.print(servo_index + 1);
          Serial.print(": ");
          Serial.println(servo_positions[servo_index]);
        } else {
          Serial.println("Invalid query");
        }
      }
    } else {
      handleServoCommand(c);
    }
  }
}