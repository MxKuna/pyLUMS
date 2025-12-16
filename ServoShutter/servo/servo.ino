#include <Servo.h>

// ============================================================================
// CONFIGURATION
// ============================================================================

Servo servos[4];
const uint8_t SERVO_PINS[4] = {9, 1, 0, 10};
const uint16_t PW_MIN = 500;
const uint16_t PW_MAX = 2500;
const uint16_t PW_DEFAULT = 1500;
uint16_t servo_positions[4] = {PW_DEFAULT, PW_DEFAULT, PW_DEFAULT, PW_DEFAULT};

// ============================================================================
// PROTOCOL CONSTANTS
// ============================================================================

const uint8_t PKT_START = 0xAA;
const uint8_t PKT_END = 0x55;
const uint8_t MAX_PACKET_SIZE = 32;

const uint8_t CMD_PING = 0x01;
const uint8_t CMD_SET_SERVO = 0x02;
const uint8_t CMD_GET_SERVO = 0x03;
const uint8_t CMD_GET_ALL = 0x04;
const uint8_t CMD_MOVE_STEPPED = 0x05;
const uint8_t CMD_STOP_MOVE = 0x06;
const uint8_t CMD_GET_MOVE_STATUS = 0x07;

const uint8_t RESP_OK = 0x00;
const uint8_t RESP_ERROR = 0xFF;

// ============================================================================
// DATA STRUCTURES
// ============================================================================

struct Packet {
  uint8_t cmd;
  uint8_t data[MAX_PACKET_SIZE];
  uint8_t length;
  bool valid;
};

struct SteppedMove {
  bool active;
  uint8_t servo_idx;
  uint16_t target_pw;
  uint16_t current_pw;
  uint16_t step_size_pw;
  uint32_t step_delay_ms;
  uint32_t last_step_time;
};

SteppedMove stepped_moves[4];

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

uint16_t degreesToMicroseconds(float degrees) {
  if (degrees < 0) degrees = 0;
  if (degrees > 180) degrees = 180;
  return (uint16_t)(500 + (degrees / 180.0) * 2000);
}

float microsecondsToDegrees(uint16_t microseconds) {
  if (microseconds < 500) microseconds = 500;
  if (microseconds > 2500) microseconds = 2500;
  return ((float)(microseconds - 500) / 2000.0) * 180.0;
}

bool setServoMicroseconds(uint8_t servo_idx, uint16_t microseconds) {
  if (servo_idx > 3) return false;
  if (microseconds < PW_MIN || microseconds > PW_MAX) return false;
  servos[servo_idx].writeMicroseconds(microseconds);
  servo_positions[servo_idx] = microseconds;
  return true;
}

// ============================================================================
// PACKET FUNCTIONS
// ============================================================================

void sendPacket(uint8_t cmd, uint8_t* data, uint8_t data_len) {
  uint8_t packet[MAX_PACKET_SIZE + 5];
  uint8_t idx = 0;
  
  packet[idx++] = PKT_START;
  packet[idx++] = data_len;
  packet[idx++] = cmd;
  
  for (uint8_t i = 0; i < data_len; i++) {
    packet[idx++] = data[i];
  }
  
  uint8_t checksum = data_len ^ cmd;
  for (uint8_t i = 0; i < data_len; i++) {
    checksum ^= data[i];
  }
  packet[idx++] = checksum;
  packet[idx++] = PKT_END;
  
  Serial.write(packet, idx);
  Serial.flush();
}

void sendResponse(uint8_t response_code) {
  uint8_t data[1] = {response_code};
  sendPacket(RESP_OK, data, 1);
}

Packet receivePacket() {
  Packet pkt;
  pkt.valid = false;
  pkt.length = 0;
  
  if (Serial.available() < 1) return pkt;
  
  uint8_t start = Serial.read();
  if (start != PKT_START) return pkt;
  
  unsigned long timeout = millis() + 100;
  while (Serial.available() < 1 && millis() < timeout);
  if (Serial.available() < 1) return pkt;
  
  uint8_t length = Serial.read();
  if (length > MAX_PACKET_SIZE) return pkt;
  
  timeout = millis() + 100;
  while (Serial.available() < 1 && millis() < timeout);
  if (Serial.available() < 1) return pkt;
  
  uint8_t cmd = Serial.read();
  
  timeout = millis() + 100;
  while (Serial.available() < length && millis() < timeout);
  if (Serial.available() < length) return pkt;
  
  uint8_t data[MAX_PACKET_SIZE];
  for (uint8_t i = 0; i < length; i++) {
    data[i] = Serial.read();
  }
  
  timeout = millis() + 100;
  while (Serial.available() < 2 && millis() < timeout);
  if (Serial.available() < 2) return pkt;
  
  uint8_t received_checksum = Serial.read();
  uint8_t end_marker = Serial.read();
  
  if (end_marker != PKT_END) return pkt;
  
  uint8_t expected_checksum = length ^ cmd;
  for (uint8_t i = 0; i < length; i++) {
    expected_checksum ^= data[i];
  }
  
  if (received_checksum != expected_checksum) return pkt;
  
  pkt.valid = true;
  pkt.cmd = cmd;
  pkt.length = length;
  for (uint8_t i = 0; i < length; i++) {
    pkt.data[i] = data[i];
  }
  
  return pkt;
}

// ============================================================================
// COMMAND HANDLERS
// ============================================================================

void handlePing(Packet& pkt) {
  uint8_t response[4] = {0x50, 0x4F, 0x4E, 0x47};
  sendPacket(CMD_PING, response, 4);
}

void handleSetServo(Packet& pkt) {
  if (pkt.length != 3) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint8_t servo_idx = pkt.data[0];
  uint16_t pw = (pkt.data[1] << 8) | pkt.data[2];
  
  if (setServoMicroseconds(servo_idx, pw)) {
    sendResponse(RESP_OK);
  } else {
    sendResponse(RESP_ERROR);
  }
}

void handleGetServo(Packet& pkt) {
  if (pkt.length != 1) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint8_t servo_idx = pkt.data[0];
  if (servo_idx > 3) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint8_t response[3];
  response[0] = servo_idx;
  response[1] = (servo_positions[servo_idx] >> 8) & 0xFF;
  response[2] = servo_positions[servo_idx] & 0xFF;
  
  sendPacket(CMD_GET_SERVO, response, 3);
}

void handleGetAll(Packet& pkt) {
  uint8_t response[8];
  
  for (uint8_t i = 0; i < 4; i++) {
    response[i*2] = (servo_positions[i] >> 8) & 0xFF;
    response[i*2 + 1] = servo_positions[i] & 0xFF;
  }
  
  sendPacket(CMD_GET_ALL, response, 8);
}

void handleMoveStep(Packet& pkt) {
  if (pkt.length != 6) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint8_t servo_idx = pkt.data[0];
  if (servo_idx > 3) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint16_t target_deg_100 = (pkt.data[1] << 8) | pkt.data[2];
  uint8_t step_deg_100 = pkt.data[3];
  uint16_t delay_ms = (pkt.data[4] << 8) | pkt.data[5];
  
  float target_degrees = target_deg_100 / 100.0;
  float step_degrees = step_deg_100 / 100.0;
  
  uint16_t target_pw = degreesToMicroseconds(target_degrees);
  float pw_per_degree = 2000.0 / 180.0;
  uint16_t step_pw = (uint16_t)(step_degrees * pw_per_degree);
  
  if (step_pw == 0) step_pw = 1;
  
  SteppedMove* move = &stepped_moves[servo_idx];
  move->active = true;
  move->servo_idx = servo_idx;
  move->target_pw = target_pw;
  move->current_pw = servo_positions[servo_idx];
  move->step_size_pw = step_pw;
  move->step_delay_ms = delay_ms;
  move->last_step_time = millis();
  
  sendResponse(RESP_OK);
}

void handleStopMove(Packet& pkt) {
  if (pkt.length != 1) {
    sendResponse(RESP_ERROR);
    return;
  }
  
  uint8_t servo_idx = pkt.data[0];
  
  if (servo_idx == 0xFF) {
    for (uint8_t i = 0; i < 4; i++) {
      stepped_moves[i].active = false;
    }
  } else if (servo_idx <= 3) {
    stepped_moves[servo_idx].active = false;
  } else {
    sendResponse(RESP_ERROR);
    return;
  }
  
  sendResponse(RESP_OK);
}

void handleGetMoveStatus(Packet& pkt) {
  uint8_t response[12];
  
  for (uint8_t i = 0; i < 4; i++) {
    response[i] = stepped_moves[i].active ? 1 : 0;
  }
  
  for (uint8_t i = 0; i < 4; i++) {
    float current_deg = microsecondsToDegrees(servo_positions[i]);
    uint16_t deg_100 = (uint16_t)(current_deg * 100);
    response[4 + i*2] = (deg_100 >> 8) & 0xFF;
    response[4 + i*2 + 1] = deg_100 & 0xFF;
  }
  
  sendPacket(CMD_GET_MOVE_STATUS, response, 12);
}

void processSteppedMoves() {
  uint32_t current_time = millis();
  
  for (uint8_t i = 0; i < 4; i++) {
    SteppedMove* move = &stepped_moves[i];
    
    if (!move->active) continue;
    
    if (current_time - move->last_step_time >= move->step_delay_ms) {
      move->last_step_time = current_time;
      
      int32_t diff = move->target_pw - move->current_pw;
      
      if (abs(diff) <= move->step_size_pw) {
        move->current_pw = move->target_pw;
        move->active = false;
      } else {
        if (diff > 0) {
          move->current_pw += move->step_size_pw;
        } else {
          move->current_pw -= move->step_size_pw;
        }
      }
      
      setServoMicroseconds(move->servo_idx, move->current_pw);
    }
  }
}

// ============================================================================
// MAIN
// ============================================================================

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);
  
  for (uint8_t i = 0; i < 4; i++) {
    stepped_moves[i].active = false;
    stepped_moves[i].servo_idx = i;
    servos[i].attach(SERVO_PINS[i]);
    servos[i].writeMicroseconds(PW_DEFAULT);
  }
  
  delay(500);
  
  uint8_t init_data[5] = {0x49, 0x4E, 0x49, 0x54, 0x00};
  sendPacket(0xFF, init_data, 5);
}

void loop() {
  processSteppedMoves();
  
  Packet pkt = receivePacket();
  
  if (pkt.valid) {
    switch(pkt.cmd) {
      case CMD_PING:
        handlePing(pkt);
        break;
      case CMD_SET_SERVO:
        handleSetServo(pkt);
        break;
      case CMD_GET_SERVO:
        handleGetServo(pkt);
        break;
      case CMD_GET_ALL:
        handleGetAll(pkt);
        break;
      case CMD_MOVE_STEPPED:
        handleMoveStep(pkt);
        break;
      case CMD_STOP_MOVE:
        handleStopMove(pkt);
        break;
      case CMD_GET_MOVE_STATUS:
        handleGetMoveStatus(pkt);
        break;
      default:
        sendResponse(RESP_ERROR);
        break;
    }
  }
  
  delay(1);
}
