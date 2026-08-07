// ============================================================================
//  ibooster_sniffer  —  READ-ONLY CAN sniffer for the Bosch / Tesla iBooster
//  v1.0.0
// ============================================================================
//
//  Target : ESP32-S3 (Lonely Binary Dev Module — same board + transceiver
//           wiring as the idrive-controller bench board)
//  Bus    : 500 kbps, standard + extended IDs, ACCEPT ALL
//  Host   : slcan (LAWICEL) subset — works with python-can bustype='slcan',
//           can-utils slcand, SavvyCAN, and canclaude.
//
//  ---------------------------------------------------------------------------
//  THIS FIRMWARE CANNOT TRANSMIT AN APPLICATION FRAME.
//  ---------------------------------------------------------------------------
//  twai_transmit() is not called anywhere in this file, and the slcan transmit
//  commands (t / T / r / R) are deliberately NOT implemented — they answer BEL
//  and are counted as refusals. This is the whole point: the device under test
//  is a brake actuator. Do not "just add" a transmit path to this sketch. If
//  you ever need to command the iBooster, that belongs in a separate, clearly
//  named sketch with its own safety interlocks.
//
//  ---------------------------------------------------------------------------
//  WIRING (matches the idrive-controller bench board)
//  ---------------------------------------------------------------------------
//    SN65HVD230 CTX  -> ESP32 GPIO4      (TWAI TX — held recessive, never used
//                                         to send a data frame, but the pin is
//                                         still required for ACK bits)
//    SN65HVD230 CRX  -> ESP32 GPIO8
//    SN65HVD230 3V3  -> ESP32 3V3        (3.3V native — NOT MCP2551)
//    SN65HVD230 GND  -> ESP32 GND  -> iBooster GND (pin 9, VERIFY)
//    SN65HVD230 CANH -> iBooster CAN-H
//    SN65HVD230 CANL -> iBooster CAN-L
//
//    Vehicle CAN: pin 25 = H, pin 16 = L   } HYPOTHESIS — see docs/PINOUT.md,
//    YAW CAN    : pin 18 = H, pin 10 = L   } confirm with a meter first.
//
//    TERMINATION: the iBooster has NO internal termination on either bus.
//    On the bench (and in the 944, where the sniffer is the only other node)
//    you need 120R at BOTH ends: one on the transceiver breakout, one across
//    H/L at the booster connector. Unpowered, H-to-L should read ~60R.
//    This is the same 2-node rule as idrive-controller, and the opposite of
//    the "never terminate when tapping a live car bus" rule in canclaude.
//
//  ---------------------------------------------------------------------------
//  THE ACK TRAP — read this before deciding the booster is dead
//  ---------------------------------------------------------------------------
//  A CAN node whose frame is never ACKed retransmits it forever, climbs its TX
//  error counter, goes error-passive, then bus-off. On a 2-node bus a
//  LISTEN-ONLY sniffer never ACKs, so the iBooster talks once and then falls
//  silent. That looks exactly like dead hardware.
//
//    'L' = open LISTEN_ONLY  — truly passive, no ACK, no error frames.
//                              Use it to confirm the bitrate is right.
//    'O' = open NORMAL       — ACKs, sends NO application frames.
//                              Use it for every real capture.
//
//  ACK is a link-layer bit, not a command. NORMAL mode here is still read-only
//  in every sense that matters for a brake actuator.
//
//  Open LISTEN_ONLY first. A sniffer running at the WRONG bitrate in NORMAL
//  mode spews error frames and genuinely does disturb the bus.
//
//  ---------------------------------------------------------------------------
//  SERIAL COMMANDS (CR-terminated; CR = ok, BEL = error)
//  ---------------------------------------------------------------------------
//    S6      set 500 kbps   (the only rate accepted — anything else is BEL)
//    O       open, NORMAL mode (ACK only, no application TX)   <- captures
//    L       open, LISTEN_ONLY mode (fully passive)            <- bitrate check
//    C       close
//    Z0/Z1   timestamps off / on (16-bit ms, appended before CR)
//    F       status flags byte
//    V v N   version / hw version / serial
//    h       toggle HUMAN mode (plain-text dump + 1 Hz bus health)
//    ?       help
//    t T r R REFUSED — answers BEL. There is no transmit path.
//
//  HUMAN mode is for Phase 2 of BENCH_PLAN.md ("does it talk at all"). It
//  prints a bus-health line every second even when no frames arrive, so
//  bus-off and error-passive are visible instead of looking like silence.
//  Leave it OFF when a host tool is attached — it is not valid slcan.
//
// ============================================================================

#include <Arduino.h>
#include "driver/twai.h"

#define FW_VERSION "1.0.0"

// ---------------------------------------------------------------- pins ------
#define CTX_PIN 4  // SN65HVD230 CTX
#define CRX_PIN 8  // SN65HVD230 CRX
#define LED_PIN 48 // onboard NeoPixel (Lonely Binary ESP32-S3)

// Pins to avoid on this board: 19/20 (USB), 26-37 (flash + OPI PSRAM),
// 0/45/46 (strapping), 43/44 (UART0).

#define RX_QUEUE_LEN 64 // deep: a busy 500k bus bursts hard
#define MAX_RX_PER_LOOP 32
#define CMD_BUF_LEN 32

static const char CR = '\r';
static const char BEL = '\a';

// --------------------------------------------------------------- state ------
static bool busOpen = false;
static bool listenOnly = false;
static bool timestamps = false;
static bool humanMode = false;

static uint32_t framesTotal = 0;
static uint32_t refusedTx = 0; // t/T/r/R attempts, for the record
static uint32_t lastFrameMs = 0;
static uint32_t lastHealthMs = 0;
static uint32_t lastLedMs = 0;

static char cmdBuf[CMD_BUF_LEN];
static uint8_t cmdLen = 0;

// ------------------------------------------------------------ helpers -------
static inline char hexDigit(uint8_t v) {
  return (char)(v < 10 ? ('0' + v) : ('A' + v - 10));
}

static void setLed(uint8_t r, uint8_t g, uint8_t b) {
  rgbLedWrite(LED_PIN, r, g, b); // core 3.x name; neopixelWrite() is deprecated
}

static const char *stateName(twai_state_t s) {
  switch (s) {
    case TWAI_STATE_STOPPED:  return "STOPPED";
    case TWAI_STATE_RUNNING:  return "RUNNING";
    case TWAI_STATE_BUS_OFF:  return "BUS-OFF";
    case TWAI_STATE_RECOVERING: return "RECOVERING";
  }
  return "?";
}

// --------------------------------------------------------- bus control ------
static bool busInstall(bool wantListenOnly) {
  twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(
      (gpio_num_t)CTX_PIN, (gpio_num_t)CRX_PIN,
      wantListenOnly ? TWAI_MODE_LISTEN_ONLY : TWAI_MODE_NORMAL);
  g.rx_queue_len = RX_QUEUE_LEN;
  g.tx_queue_len = 0; // no TX queue: nothing can be queued, by construction

  twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS();
  twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  if (twai_driver_install(&g, &t, &f) != ESP_OK) return false;
  if (twai_start() != ESP_OK) {
    twai_driver_uninstall();
    return false;
  }
  twai_reconfigure_alerts(TWAI_ALERT_ABOVE_ERR_WARN | TWAI_ALERT_ERR_PASS |
                              TWAI_ALERT_BUS_OFF | TWAI_ALERT_BUS_ERROR |
                              TWAI_ALERT_RX_QUEUE_FULL,
                          NULL);
  busOpen = true;
  listenOnly = wantListenOnly;
  lastFrameMs = millis();
  return true;
}

static void busClose() {
  if (!busOpen) return;
  twai_stop();
  twai_driver_uninstall();
  busOpen = false;
}

// ------------------------------------------------------------- output -------
// slcan: tIIILDD..[TTTT]<CR>  /  TIIIIIIIILDD..[TTTT]<CR>  (r/R for RTR)
static void emitSlcan(const twai_message_t &m) {
  char out[40];
  uint8_t n = 0;

  if (m.extd) {
    out[n++] = m.rtr ? 'R' : 'T';
    for (int8_t s = 28; s >= 0; s -= 4) out[n++] = hexDigit((m.identifier >> s) & 0xF);
  } else {
    out[n++] = m.rtr ? 'r' : 't';
    for (int8_t s = 8; s >= 0; s -= 4) out[n++] = hexDigit((m.identifier >> s) & 0xF);
  }

  out[n++] = hexDigit(m.data_length_code & 0xF);

  if (!m.rtr) {
    for (uint8_t i = 0; i < m.data_length_code && i < 8; i++) {
      out[n++] = hexDigit(m.data[i] >> 4);
      out[n++] = hexDigit(m.data[i] & 0xF);
    }
  }

  if (timestamps) {
    uint16_t ts = (uint16_t)(millis() & 0xFFFF);
    for (int8_t s = 12; s >= 0; s -= 4) out[n++] = hexDigit((ts >> s) & 0xF);
  }

  out[n++] = CR;
  Serial.write((const uint8_t *)out, n);
}

static void emitHuman(const twai_message_t &m) {
  char out[80];
  uint8_t n = (uint8_t)snprintf(out, sizeof(out), "%8lu  %s %0*lX [%u] ",
                                (unsigned long)millis(), m.extd ? "EXT" : "STD",
                                m.extd ? 8 : 3, (unsigned long)m.identifier,
                                m.data_length_code);
  if (m.rtr) {
    n += (uint8_t)snprintf(out + n, sizeof(out) - n, "RTR");
  } else {
    for (uint8_t i = 0; i < m.data_length_code && i < 8; i++)
      n += (uint8_t)snprintf(out + n, sizeof(out) - n, "%02X ", m.data[i]);
  }
  out[n++] = '\n';
  Serial.write((const uint8_t *)out, n);
}

// 1 Hz in HUMAN mode: makes bus-off / error-passive visible instead of silent.
static void emitHealth() {
  twai_status_info_t st;
  if (twai_get_status_info(&st) != ESP_OK) return;

  Serial.printf(
      "--- %s%s  state=%s  txerr=%lu rxerr=%lu  buserr=%lu arblost=%lu "
      "rxmissed=%lu  frames=%lu\n",
      busOpen ? "OPEN " : "CLOSED ", busOpen ? (listenOnly ? "(listen-only)" : "(ACK)") : "",
      stateName(st.state), (unsigned long)st.tx_error_counter,
      (unsigned long)st.rx_error_counter, (unsigned long)st.bus_error_count,
      (unsigned long)st.arb_lost_count, (unsigned long)st.rx_missed_count,
      (unsigned long)framesTotal);

  if (busOpen && framesTotal == 0 && listenOnly &&
      (millis() - lastFrameMs) > 5000) {
    Serial.println(
        "    hint: silent in listen-only is expected on a 2-node bus once the "
        "booster gives up on ACK. Send 'C' then 'O' to capture with ACK.");
  }
  if (st.state == TWAI_STATE_BUS_OFF) {
    Serial.println("    BUS-OFF: check 120R at both ends, H/L not swapped, "
                   "common ground, and that the bitrate really is 500k.");
  }
}

static void printHelp() {
  Serial.printf(
      "\nibooster_sniffer v%s  —  READ-ONLY. No transmit path exists.\n"
      "  S6  500 kbps (only rate)      O  open NORMAL (ACK, no app TX)\n"
      "  C   close                     L  open LISTEN-ONLY (fully passive)\n"
      "  Z0/Z1 timestamps off/on       F  status flags\n"
      "  V/v/N version/hw/serial       h  toggle HUMAN mode\n"
      "  t/T/r/R  REFUSED — this is a brake actuator.\n"
      "Open L first to confirm the bitrate, then C and O to capture.\n\n",
      FW_VERSION);
}

// ------------------------------------------------------------ commands ------
static void handleCommand(const char *c, uint8_t len) {
  if (len == 0) { Serial.write(CR); return; }

  switch (c[0]) {
    // ---- refused: there is no transmit path ----
    case 't': case 'T': case 'r': case 'R':
      refusedTx++;
      if (humanMode)
        Serial.printf("REFUSED transmit command '%c' (#%lu) — read-only build\n",
                      c[0], (unsigned long)refusedTx);
      Serial.write(BEL);
      return;

    case 'S':
      if (len >= 2 && c[1] == '6') Serial.write(CR);  // 500k
      else Serial.write(BEL);                          // no other rate
      return;

    case 'O':
      if (busOpen) busClose();
      Serial.write(busInstall(false) ? CR : BEL);
      return;

    case 'L':
      if (busOpen) busClose();
      Serial.write(busInstall(true) ? CR : BEL);
      return;

    case 'C':
      busClose();
      Serial.write(CR);
      return;

    case 'Z':
      if (len >= 2 && (c[1] == '0' || c[1] == '1')) {
        timestamps = (c[1] == '1');
        Serial.write(CR);
      } else Serial.write(BEL);
      return;

    case 'F': {
      uint8_t flags = 0;
      twai_status_info_t st;
      if (twai_get_status_info(&st) == ESP_OK) {
        if (st.rx_missed_count) flags |= 0x08;      // RX overrun
        if (st.rx_error_counter > 96 ||
            st.tx_error_counter > 96) flags |= 0x20; // error passive
        if (st.state == TWAI_STATE_BUS_OFF) flags |= 0x80;
      }
      Serial.printf("F%02X", flags);
      Serial.write(CR);
      return;
    }

    case 'V': Serial.print("V1010"); Serial.write(CR); return;
    case 'v': Serial.print("v1013"); Serial.write(CR); return;
    case 'N': Serial.print("NIB01"); Serial.write(CR); return;

    // accept-and-ignore so host tools that always send these don't stall
    case 'M': case 'm': case 's': Serial.write(CR); return;

    case 'h':
      humanMode = !humanMode;
      if (humanMode) {
        Serial.printf("\nHUMAN mode ON (not valid slcan). Bus is %s.\n",
                      busOpen ? (listenOnly ? "OPEN listen-only" : "OPEN with ACK")
                              : "CLOSED — send O to capture");
      }
      return;

    case '?': printHelp(); return;

    default:
      Serial.write(BEL);
      return;
  }
}

// ---------------------------------------------------------------- setup -----
void setup() {
  Serial.begin(115200);
  // Load-bearing: hardware USB CDC blocks on write with no host draining the
  // FIFO (~2 s stalls). Same trap that made the idrive board look like flaky
  // hardware. See esp32s3-usb-cdc-write-stall.
  Serial.setTxTimeoutMs(0);

  setLed(0, 0, 24); // dim blue = alive, bus closed
  delay(150);
  printHelp();
}

// ----------------------------------------------------------------- loop -----
void loop() {
  // --- drain RX (bounded so serial input never starves) ---
  if (busOpen) {
    twai_message_t m;
    for (uint8_t i = 0; i < MAX_RX_PER_LOOP; i++) {
      if (twai_receive(&m, 0) != ESP_OK) break;
      framesTotal++;
      lastFrameMs = millis();
      if (humanMode) emitHuman(m);
      else emitSlcan(m);
    }

    uint32_t alerts = 0;
    if (twai_read_alerts(&alerts, 0) == ESP_OK && alerts && humanMode) {
      if (alerts & TWAI_ALERT_BUS_OFF)
        Serial.println("!! BUS-OFF — no other node is ACKing, or wiring/bitrate is wrong");
      else if (alerts & TWAI_ALERT_ERR_PASS)
        Serial.println("!! error-passive");
      else if (alerts & TWAI_ALERT_RX_QUEUE_FULL)
        Serial.println("!! RX queue full — frames dropped");
    }
  }

  // --- serial commands (CR or LF terminated) ---
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\r' || ch == '\n') {
      cmdBuf[cmdLen] = '\0';
      handleCommand(cmdBuf, cmdLen);
      cmdLen = 0;
    } else if (cmdLen < CMD_BUF_LEN - 1) {
      cmdBuf[cmdLen++] = ch;
    }
  }

  // --- 1 Hz health line, HUMAN mode only ---
  uint32_t now = millis();
  if (humanMode && now - lastHealthMs >= 1000) {
    lastHealthMs = now;
    emitHealth();
  }

  // --- status LED ---
  if (now - lastLedMs >= 100) {
    lastLedMs = now;
    if (!busOpen) {
      setLed(0, 0, 24); // blue   : closed
    } else {
      twai_status_info_t st;
      twai_get_status_info(&st);
      if (st.state == TWAI_STATE_BUS_OFF) setLed(40, 0, 0);        // red
      else if (now - lastFrameMs < 500)   setLed(0, 30, listenOnly ? 30 : 0);
      else                                setLed(30, 12, 0);       // amber: quiet
    }
  }
}
