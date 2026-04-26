/*
 * ╔══════════════════════════════════════════════════╗
 * ║   GestureFX Arduino Controller                  ║
 * ║   Receives single-byte commands from Python     ║
 * ║   and drives LEDs, fan relay, and mist relay    ║
 * ╚══════════════════════════════════════════════════╝
 *
 * WIRING:
 *   Pin 9  → Red   LED strip   (PWM, via MOSFET)
 *   Pin 10 → Green LED strip   (PWM, via MOSFET)
 *   Pin 11 → Blue  LED strip   (PWM, via MOSFET)
 *   Pin 4  → Fan relay (5V coil, NO terminal to fan)
 *   Pin 5  → Mist relay
 *
 * Commands received over Serial (9600 baud):
 *   'F' → Fire  : red LEDs ON, fan ON
 *   'W' → Water : blue LEDs ON, mist ON
 *   'B' → Beam  : white flash
 *   'A' → Air   : white dim, fan ON
 *   'X' → Off   : all OFF
 */

// ── Pin Definitions ─────────────────────────────────────
const int PIN_R    = 9;
const int PIN_G    = 10;
const int PIN_B    = 11;
const int PIN_FAN  = 4;
const int PIN_MIST = 5;

// ── State ────────────────────────────────────────────────
char lastCmd = 'X';
unsigned long beamStart = 0;
bool beamActive = false;

// ── Helpers ──────────────────────────────────────────────
void setLED(int r, int g, int b) {
  analogWrite(PIN_R, r);
  analogWrite(PIN_G, g);
  analogWrite(PIN_B, b);
}

void allOff() {
  setLED(0, 0, 0);
  digitalWrite(PIN_FAN,  LOW);
  digitalWrite(PIN_MIST, LOW);
}

// ── Setup ────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  pinMode(PIN_R,    OUTPUT);
  pinMode(PIN_G,    OUTPUT);
  pinMode(PIN_B,    OUTPUT);
  pinMode(PIN_FAN,  OUTPUT);
  pinMode(PIN_MIST, OUTPUT);
  allOff();
  Serial.println("GestureFX Arduino Ready");
}

// ── Loop ─────────────────────────────────────────────────
void loop() {
  // ── Handle incoming command ────────────────────────────
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd != lastCmd) {
      lastCmd = cmd;
      allOff();
      beamActive = false;

      switch (cmd) {
        case 'F':  // Fire: warm red-orange, fan on
          setLED(255, 80, 0);
          digitalWrite(PIN_FAN, HIGH);
          break;

        case 'W':  // Water: cool blue, mist on
          setLED(0, 60, 255);
          digitalWrite(PIN_MIST, HIGH);
          break;

        case 'B':  // Beam: bright white flash
          beamActive = true;
          beamStart  = millis();
          setLED(255, 255, 255);
          break;

        case 'A':  // Air: pale white, fan on
          setLED(80, 80, 100);
          digitalWrite(PIN_FAN, HIGH);
          break;

        case 'X':  // Off
        default:
          allOff();
          break;
      }
    }
  }

  // ── Beam pulsing animation ─────────────────────────────
  if (beamActive) {
    unsigned long elapsed = millis() - beamStart;
    // Pulse every 200ms
    int phase = (elapsed / 200) % 2;
    if (phase == 0) {
      setLED(255, 255, 255);  // bright
    } else {
      setLED(100, 120, 255);  // blue tint
    }
  }

  // ── Fire flicker ──────────────────────────────────────
  if (lastCmd == 'F') {
    int flicker = random(200, 255);
    int green   = random(40, 100);
    setLED(flicker, green, 0);
    delay(40);
  }
}
