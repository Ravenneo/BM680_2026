#include <Wire.h>

const byte GEIGER_PIN = 2;       // INT0, falling edge pulse from tube circuit
const byte LCD_I2C_ADDR = 0x27;   // Inferred from the original firmware backup
const byte TUBE_SEL_PIN = A0;    // LOW selects secondary tube ratio if wired
const byte ALARM_PIN = 10;       // keep LOW to disable software alarm/buzzer output
const byte BUTTON_PIN = 11;      // not used here, kept pulled up
const byte LED_PIN = 13;

const uint16_t PRIMARY_CPM_PER_USV_X100 = 17543;   // SBM-20 style: 175.43 CPM per uSv/h
const uint16_t SECONDARY_CPM_PER_USV_X100 = 10000; // LND712-style fallback from original code
const byte WINDOW_SECONDS = 60;
const unsigned long SERIAL_PERIOD_MS = 1000;
const unsigned long LCD_PERIOD_MS = 5000;

const byte LCD_BACKLIGHT = 0x08;
const byte LCD_ENABLE = 0x04;
const byte LCD_RW = 0x02;
const byte LCD_RS = 0x01;

volatile uint16_t pulsesThisSecond = 0;
volatile uint32_t totalPulses = 0;

uint16_t secondBins[WINDOW_SECONDS];
byte binIndex = 0;
byte binsFilled = 0;
uint32_t rollingCounts = 0;
uint16_t lastCps = 0;
uint32_t lastCpm = 0;
uint32_t lastUsvCenti = 0;
uint32_t lastTotal = 0;
uint16_t cpmPerUsvX100 = PRIMARY_CPM_PER_USV_X100;
unsigned long lastSerialAt = 0;
unsigned long lastLcdAt = 0;

void lcdExpanderWrite(byte value) {
  Wire.beginTransmission(LCD_I2C_ADDR);
  Wire.write(value | LCD_BACKLIGHT);
  Wire.endTransmission();
}

void lcdPulseEnable(byte value) {
  lcdExpanderWrite(value | LCD_ENABLE);
  delayMicroseconds(1);
  lcdExpanderWrite(value & ~LCD_ENABLE);
  delayMicroseconds(50);
}

void lcdWrite4Bits(byte value) {
  lcdPulseEnable(value);
}

void lcdSend(byte value, byte mode) {
  lcdWrite4Bits((value & 0xF0) | mode);
  lcdWrite4Bits(((value << 4) & 0xF0) | mode);
}

void lcdCommand(byte value) {
  lcdSend(value, 0);
}

void lcdWriteChar(char value) {
  lcdSend((byte)value, LCD_RS);
}

void lcdClear() {
  lcdCommand(0x01);
  delayMicroseconds(2000);
}

void lcdSetCursor(byte col, byte row) {
  const byte rowOffsets[] = {0x00, 0x40};
  if (row > 1) row = 1;
  lcdCommand(0x80 | (col + rowOffsets[row]));
}

void lcdBegin() {
  Wire.begin();
  delay(50);

  lcdExpanderWrite(0);
  delay(100);

  lcdWrite4Bits(0x30);
  delayMicroseconds(4500);
  lcdWrite4Bits(0x30);
  delayMicroseconds(4500);
  lcdWrite4Bits(0x30);
  delayMicroseconds(150);
  lcdWrite4Bits(0x20);

  lcdCommand(0x28); // 4-bit, 2 lines, 5x8 font
  lcdCommand(0x08); // display off
  lcdClear();
  lcdCommand(0x06); // entry mode: increment, no shift
  lcdCommand(0x0C); // display on, cursor off, blink off
}

void geigerPulse() {
  pulsesThisSecond++;
  totalPulses++;
}

void printUsv(Stream &out, uint32_t centi) {
  out.print(centi / 100);
  out.print('.');
  byte frac = centi % 100;
  if (frac < 10) out.print('0');
  out.print(frac);
}

void lcdPrintPadded(const char *text) {
  byte count = 0;
  while (*text && count < 16) {
    lcdWriteChar(*text++);
    count++;
  }
  while (count++ < 16) lcdWriteChar(' ');
}

void updateLcd() {
  char line[17];

  lcdSetCursor(0, 0);
  snprintf(line, sizeof(line), "CPM %-12lu", lastCpm);
  lcdPrintPadded(line);

  lcdSetCursor(0, 1);
  snprintf(line, sizeof(line), "Dosis %lu.%02u uSv", lastUsvCenti / 100, (unsigned)(lastUsvCenti % 100));
  lcdPrintPadded(line);
}

void printHeader() {
  Serial.println(F("geiger_usb_quiet"));
  Serial.println(F("format: ms,cps,cpm,usv_h,total"));
}

void setup() {
  pinMode(GEIGER_PIN, INPUT_PULLUP);
  pinMode(TUBE_SEL_PIN, INPUT_PULLUP);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(ALARM_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(ALARM_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  cpmPerUsvX100 = digitalRead(TUBE_SEL_PIN) == LOW ? SECONDARY_CPM_PER_USV_X100 : PRIMARY_CPM_PER_USV_X100;

  Serial.begin(9600);
  printHeader();

  lcdBegin();
  lcdSetCursor(0, 0);
  lcdPrintPadded("Monitor Geiger");
  lcdSetCursor(0, 1);
  lcdPrintPadded("Sonido OFF");

  attachInterrupt(digitalPinToInterrupt(GEIGER_PIN), geigerPulse, FALLING);

  unsigned long now = millis();
  lastSerialAt = now;
  lastLcdAt = now;
}

void loop() {
  unsigned long now = millis();

  if ((unsigned long)(now - lastSerialAt) >= SERIAL_PERIOD_MS) {
    lastSerialAt += SERIAL_PERIOD_MS;

    noInterrupts();
    uint16_t cps = pulsesThisSecond;
    pulsesThisSecond = 0;
    uint32_t total = totalPulses;
    interrupts();

    rollingCounts -= secondBins[binIndex];
    secondBins[binIndex] = cps;
    rollingCounts += cps;
    binIndex = (binIndex + 1) % WINDOW_SECONDS;
    if (binsFilled < WINDOW_SECONDS) binsFilled++;

    uint32_t cpm = binsFilled == 0 ? 0 : (rollingCounts * 60UL) / binsFilled;
    uint32_t usvCenti = (cpm * 10000UL + (cpmPerUsvX100 / 2)) / cpmPerUsvX100;

    lastCps = cps;
    lastCpm = cpm;
    lastUsvCenti = usvCenti;
    lastTotal = total;

    digitalWrite(ALARM_PIN, LOW);
    digitalWrite(LED_PIN, LOW);

    Serial.print(now);
    Serial.print(',');
    Serial.print(lastCps);
    Serial.print(',');
    Serial.print(lastCpm);
    Serial.print(',');
    printUsv(Serial, lastUsvCenti);
    Serial.print(',');
    Serial.println(lastTotal);
  }

  if ((unsigned long)(now - lastLcdAt) >= LCD_PERIOD_MS) {
    lastLcdAt += LCD_PERIOD_MS;
    updateLcd();
  }
}
