"""
╔══════════════════════════════════════════════════════════════╗
║         GESTURE FX — Real-Time Hand Gesture Effects          ║
║   Uses OpenCV + MediaPipe for tracking, NumPy for particles  ╠
╚══════════════════════════════════════════════════════════════╝

SETUP:
    pip install opencv-python mediapipe numpy pygame pyserial

OPTIONAL (Arduino):
    pip install pyserial
    Flash arduino_controller.ino to your board

RUN:
    python gesture_effects.py
    python gesture_effects.py --arduino /dev/ttyUSB0   # with Arduino
    python gesture_effects.py --no-sound               # disable audio
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import math
import random
import argparse
from collections import deque
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum, auto

# ─────────────────────────────────────────────
#  Optional dependencies (graceful fallback)
# ─────────────────────────────────────────────
try:
    import pygame
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False
    print("[WARN] pygame not found — sound disabled. Install with: pip install pygame")

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[WARN] pyserial not found — Arduino disabled. Install with: pip install pyserial")


# ═══════════════════════════════════════════════
#  GESTURE DEFINITIONS
# ═══════════════════════════════════════════════

class Gesture(Enum):
    NONE        = auto()
    OPEN_PALM   = auto()   # All 5 fingers extended → Water
    FIST        = auto()   # All fingers curled     → Fire
    POINTING    = auto()   # Only index extended    → Energy Beam
    SWIPE_LEFT  = auto()   # Horizontal fast motion → Wind (left)
    SWIPE_RIGHT = auto()   # Horizontal fast motion → Wind (right)
    PEACE       = auto()   # Index + middle extended (bonus gesture)


# ═══════════════════════════════════════════════
#  PARTICLE BASE CLASS
# ═══════════════════════════════════════════════

@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float          # 0.0 → 1.0 (1 = just born)
    max_life: float
    size: float
    color: Tuple[int, int, int]

    def update(self, dt: float) -> bool:
        """Update particle. Returns False when dead."""
        self.x  += self.vx * dt
        self.y  += self.vy * dt
        self.life -= dt / self.max_life
        return self.life > 0

    @property
    def alpha(self) -> float:
        return max(0.0, self.life)


# ═══════════════════════════════════════════════
#  PARTICLE SYSTEMS
# ═══════════════════════════════════════════════

class ParticleSystem:
    """Base class for all particle effects."""

    def __init__(self):
        self.particles: List[Particle] = []

    def emit(self, x: float, y: float, **kwargs):
        raise NotImplementedError

    def update(self, dt: float):
        self.particles = [p for p in self.particles if p.update(dt)]

    def draw(self, frame: np.ndarray):
        raise NotImplementedError

    def clear(self):
        self.particles.clear()


class FireSystem(ParticleSystem):
    """
    Upward-rising fire particles with orange/red/yellow palette.
    Each particle starts large at the fist center and shrinks as it rises.
    """

    def emit(self, x: float, y: float, intensity: float = 1.0):
        count = int(random.randint(4, 8) * intensity)
        for _ in range(count):
            angle  = random.uniform(-math.pi / 3, -2 * math.pi / 3)  # mostly upward
            speed  = random.uniform(60, 160) * intensity
            vx     = math.cos(angle) * speed + random.uniform(-20, 20)
            vy     = math.sin(angle) * speed
            life   = random.uniform(0.5, 1.2)
            size   = random.uniform(6, 18) * intensity

            # Color: deep red → orange → yellow (based on randomness)
            r = 255
            g = random.randint(40, 200)
            b = random.randint(0, 30)
            self.particles.append(Particle(x, y, vx, vy, 1.0, life, size, (b, g, r)))

    def draw(self, frame: np.ndarray):
        overlay = frame.copy()
        for p in self.particles:
            alpha  = p.alpha
            radius = max(1, int(p.size * alpha))
            cx, cy = int(p.x), int(p.y)
            if 0 < cx < frame.shape[1] and 0 < cy < frame.shape[0]:
                # Glow: draw larger translucent circle first
                cv2.circle(overlay, (cx, cy), radius * 2, p.color, -1, cv2.LINE_AA)
                cv2.circle(overlay, (cx, cy), radius,     (200, 230, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)


class WaterSystem(ParticleSystem):
    """
    Downward-flowing water droplets with blue/cyan palette.
    Spawns from each fingertip of an open palm.
    """

    def emit(self, x: float, y: float, intensity: float = 1.0):
        count = int(random.randint(3, 6) * intensity)
        for _ in range(count):
            vx   = random.uniform(-30, 30)
            vy   = random.uniform(80, 200) * intensity  # fall down
            life = random.uniform(0.6, 1.4)
            size = random.uniform(3, 10)

            b = 255
            g = random.randint(160, 230)
            r = random.randint(0, 60)
            self.particles.append(Particle(x, y, vx, vy, 1.0, life, size, (b, g, r)))

    def draw(self, frame: np.ndarray):
        overlay = frame.copy()
        for p in self.particles:
            alpha  = p.alpha
            radius = max(1, int(p.size * alpha))
            cx, cy = int(p.x), int(p.y)
            # Teardrop simulation: draw elongated oval
            if 0 < cx < frame.shape[1] and 0 < cy < frame.shape[0]:
                cv2.ellipse(overlay, (cx, cy), (radius, max(1, radius * 2)),
                            0, 0, 360, p.color, -1, cv2.LINE_AA)
                # Highlight
                cv2.circle(overlay, (cx - radius // 3, cy - radius // 2),
                           max(1, radius // 3), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)


class BeamSystem:
    """
    Energy beam from pointing finger — rendered as a pulsing laser line
    with glow and sparks at the tip.
    """

    def __init__(self):
        self.sparks: List[Particle] = []
        self.active  = False
        self.pulse   = 0.0

    def emit(self, tip_x: float, tip_y: float,
             dir_x: float, dir_y: float, frame_w: int, frame_h: int):
        self.active = True
        self.tip_x, self.tip_y   = tip_x, tip_y
        self.dir_x, self.dir_y   = dir_x, dir_y
        self.frame_w, self.frame_h = frame_w, frame_h

        # Sparks at the beam end
        for _ in range(3):
            angle = math.atan2(dir_y, dir_x) + random.uniform(-0.4, 0.4)
            speed = random.uniform(80, 200)
            life  = random.uniform(0.2, 0.5)
            # End point of beam
            end_x = tip_x + dir_x * frame_w
            end_y = tip_y + dir_y * frame_w
            self.sparks.append(Particle(
                end_x, end_y,
                math.cos(angle) * speed,
                math.sin(angle) * speed,
                1.0, life, random.uniform(2, 6),
                (random.randint(100, 255), random.randint(200, 255), 255)
            ))

    def update(self, dt: float):
        self.pulse = (self.pulse + dt * 6) % (2 * math.pi)
        self.sparks = [p for p in self.sparks if p.update(dt)]

    def draw(self, frame: np.ndarray):
        if not self.active:
            return
        pulse_w = int(3 + 2 * math.sin(self.pulse))
        tip = (int(self.tip_x), int(self.tip_y))
        end = (int(self.tip_x + self.dir_x * self.frame_w * 2),
               int(self.tip_y + self.dir_y * self.frame_w * 2))

        overlay = frame.copy()
        # Outer glow (thick, low opacity)
        cv2.line(overlay, tip, end, (255, 220, 100), pulse_w + 12, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        overlay = frame.copy()
        # Mid glow
        cv2.line(overlay, tip, end, (180, 240, 255), pulse_w + 4, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

        # Core beam (sharp white)
        cv2.line(frame, tip, end, (255, 255, 255), pulse_w, cv2.LINE_AA)

        # Sparks
        for p in self.sparks:
            cx, cy = int(p.x), int(p.y)
            r = max(1, int(p.size * p.alpha))
            cv2.circle(frame, (cx, cy), r, p.color, -1, cv2.LINE_AA)

        self.active = False

    def clear(self):
        self.sparks.clear()
        self.active = False


class WindSystem(ParticleSystem):
    """
    Horizontal streaks simulating wind / air trails.
    Direction flips based on swipe direction.
    """

    def emit(self, x: float, y: float, direction: int = 1, intensity: float = 1.0):
        """direction: +1 = right, -1 = left"""
        count = int(random.randint(5, 10) * intensity)
        for _ in range(count):
            vx   = direction * random.uniform(150, 350) * intensity
            vy   = random.uniform(-30, 30)
            life = random.uniform(0.3, 0.8)
            size = random.uniform(2, 5)

            gray = random.randint(180, 255)
            alpha_color = (gray, gray, gray)
            # Spawn in a spread around the hand center
            sx = x + random.uniform(-60, 60)
            sy = y + random.uniform(-60, 60)
            self.particles.append(Particle(sx, sy, vx, vy, 1.0, life, size, alpha_color))

    def draw(self, frame: np.ndarray):
        overlay = frame.copy()
        for p in self.particles:
            alpha  = p.alpha
            cx, cy = int(p.x), int(p.y)
            # Draw as a short horizontal streak
            streak = int(p.size * 10 * alpha)
            ex = cx - int(p.vx * 0.04 * alpha)
            if 0 < cx < frame.shape[1] and 0 < cy < frame.shape[0]:
                thickness = max(1, int(p.size * alpha))
                cv2.line(overlay, (ex, cy), (cx, cy), p.color, thickness, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)


# ═══════════════════════════════════════════════
#  GESTURE CLASSIFIER
# ═══════════════════════════════════════════════

class GestureClassifier:
    """
    Classifies hand gesture from MediaPipe landmarks.
    Uses finger extension logic + velocity history for swipe detection.
    """

    FINGER_TIPS  = [4, 8, 12, 16, 20]   # thumb, index, middle, ring, pinky tip IDs
    FINGER_PIPS  = [2, 6, 10, 14, 18]   # corresponding PIP (knuckle) IDs

    def __init__(self, history_len: int = 12):
        # Wrist position history for velocity calculation (swipe detection)
        self.pos_history: deque = deque(maxlen=history_len)
        self.time_history: deque = deque(maxlen=history_len)

    def _finger_extended(self, lm, tip_id: int, pip_id: int, is_thumb: bool = False) -> bool:
        """Returns True if the given finger is extended."""
        tip = lm[tip_id]
        pip = lm[pip_id]
        if is_thumb:
            # Thumb: compare x coordinates (mirrored camera)
            return abs(tip.x - lm[0].x) > abs(pip.x - lm[0].x)
        else:
            # Other fingers: tip.y < pip.y means extended (image coords, y↓)
            return tip.y < pip.y - 0.02

    def classify(self, hand_landmarks, image_width: int, image_height: int) -> Tuple[Gesture, dict]:
        """
        Returns (Gesture, metadata_dict) where metadata includes:
          - wrist: (x, y) pixel position
          - fingertips: list of (x, y) pixel positions
          - velocity: (vx, vy) pixels/sec
          - index_direction: (dx, dy) unit vector from index knuckle to tip
        """
        lm = hand_landmarks.landmark

        # ── Pixel positions ──────────────────────────────────────────
        def px(lm_pt) -> Tuple[int, int]:
            return (int(lm_pt.x * image_width), int(lm_pt.y * image_height))

        wrist     = px(lm[0])
        fingertips = [px(lm[tid]) for tid in self.FINGER_TIPS]

        # ── Update velocity history ───────────────────────────────────
        now = time.time()
        self.pos_history.append(wrist)
        self.time_history.append(now)

        velocity = (0.0, 0.0)
        if len(self.pos_history) >= 4:
            dt  = self.time_history[-1] - self.time_history[0]
            if dt > 0:
                dx  = self.pos_history[-1][0] - self.pos_history[0][0]
                dy  = self.pos_history[-1][1] - self.pos_history[0][1]
                velocity = (dx / dt, dy / dt)

        # ── Finger extension flags ───────────────────────────────────
        thumb_ext  = self._finger_extended(lm, 4,  2,  is_thumb=True)
        index_ext  = self._finger_extended(lm, 8,  6)
        middle_ext = self._finger_extended(lm, 12, 10)
        ring_ext   = self._finger_extended(lm, 16, 14)
        pinky_ext  = self._finger_extended(lm, 20, 18)

        extended_count = sum([thumb_ext, index_ext, middle_ext, ring_ext, pinky_ext])

        # ── Index finger direction vector ────────────────────────────
        ix = lm[8].x - lm[6].x
        iy = lm[8].y - lm[6].y
        mag = math.sqrt(ix * ix + iy * iy) or 1e-6
        index_dir = (ix / mag, iy / mag)

        meta = {
            "wrist":           wrist,
            "fingertips":      fingertips,
            "velocity":        velocity,
            "index_direction": index_dir,
        }

        # ── Swipe detection (high horizontal velocity) ───────────────
        SWIPE_THRESHOLD = 400  # pixels/sec
        vx, vy = velocity
        if abs(vx) > SWIPE_THRESHOLD and abs(vx) > abs(vy) * 1.5:
            return (Gesture.SWIPE_RIGHT if vx > 0 else Gesture.SWIPE_LEFT), meta

        # ── Static gesture classification ────────────────────────────
        if extended_count >= 4:
            return Gesture.OPEN_PALM, meta

        if extended_count <= 1 and not index_ext:
            return Gesture.FIST, meta

        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return Gesture.PEACE, meta

        if index_ext and not middle_ext and not ring_ext and not pinky_ext:
            return Gesture.POINTING, meta

        return Gesture.NONE, meta


# ═══════════════════════════════════════════════
#  HUD OVERLAY
# ═══════════════════════════════════════════════

GESTURE_LABELS = {
    Gesture.NONE:        ("·  None",         (120, 120, 120)),
    Gesture.OPEN_PALM:   ("💧 Open Palm",    (255, 220,  80)),
    Gesture.FIST:        ("🔥 Fist",         ( 60, 100, 255)),
    Gesture.POINTING:    ("⚡ Pointing",     (255, 255, 100)),
    Gesture.SWIPE_LEFT:  ("💨 Swipe Left",   (220, 220, 255)),
    Gesture.SWIPE_RIGHT: ("💨 Swipe Right",  (220, 220, 255)),
    Gesture.PEACE:       ("✌  Peace",        (100, 255, 150)),
}

def draw_hud(frame: np.ndarray, gesture: Gesture, fps: float):
    h, w = frame.shape[:2]
    label, color = GESTURE_LABELS.get(gesture, ("Unknown", (255, 255, 255)))

    # Semi-transparent black bar at top
    bar = frame[0:50, :].copy()
    cv2.rectangle(bar, (0, 0), (w, 50), (0, 0, 0), -1)
    cv2.addWeighted(bar, 0.55, frame[0:50, :], 0.45, 0, frame[0:50, :])

    cv2.putText(frame, f"GESTURE: {label}", (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"FPS: {fps:.1f}", (w - 120, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 255, 200), 2, cv2.LINE_AA)

    # Legend at bottom
    legend_items = [
        ("Open Palm", "Water"),
        ("Fist", "Fire"),
        ("Point", "Beam"),
        ("Swipe", "Wind"),
    ]
    bar2 = frame[h - 36:h, :].copy()
    cv2.rectangle(bar2, (0, 0), (w, 36), (0, 0, 0), -1)
    cv2.addWeighted(bar2, 0.55, frame[h - 36:h, :], 0.45, 0, frame[h - 36:h, :])
    for i, (g, e) in enumerate(legend_items):
        cv2.putText(frame, f"{g}→{e}", (16 + i * 170, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 180, 180), 1, cv2.LINE_AA)


# ═══════════════════════════════════════════════
#  SOUND MANAGER
# ═══════════════════════════════════════════════

class SoundManager:
    """Manages looping ambient sound effects per gesture."""

    SOUNDS = {
        Gesture.OPEN_PALM:   "water_loop.wav",
        Gesture.FIST:        "fire_loop.wav",
        Gesture.POINTING:    "beam_loop.wav",
        Gesture.SWIPE_LEFT:  "wind_loop.wav",
        Gesture.SWIPE_RIGHT: "wind_loop.wav",
    }

    def __init__(self, sound_dir: str = "sounds"):
        self.available = False
        self._current: Optional[Gesture] = None
        if not SOUND_AVAILABLE:
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._channels = {}
            import os
            for gesture, fname in self.SOUNDS.items():
                path = os.path.join(sound_dir, fname)
                if os.path.exists(path):
                    snd = pygame.mixer.Sound(path)
                    ch  = pygame.mixer.Channel(len(self._channels))
                    self._channels[gesture] = (ch, snd)
            self.available = bool(self._channels)
            print(f"[SOUND] Loaded {len(self._channels)} sound(s).")
        except Exception as e:
            print(f"[WARN] Sound init failed: {e}")

    def play(self, gesture: Gesture):
        if not self.available or gesture == self._current:
            return
        self.stop_all()
        if gesture in self._channels:
            ch, snd = self._channels[gesture]
            ch.play(snd, loops=-1, fade_ms=200)
        self._current = gesture

    def stop_all(self):
        if not self.available:
            return
        for ch, _ in self._channels.values():
            ch.fadeout(300)
        self._current = None


# ═══════════════════════════════════════════════
#  ARDUINO CONTROLLER (optional)
# ═══════════════════════════════════════════════

class ArduinoController:
    """
    Sends single-byte commands to Arduino over serial.
    Commands:
      'F' → Fire   (LEDs red, activate fan)
      'W' → Water  (LEDs blue, activate mist)
      'B' → Beam   (LEDs white flash)
      'A' → Air    (activate fan)
      'X' → Off
    """

    COMMANDS = {
        Gesture.FIST:        b'F',
        Gesture.OPEN_PALM:   b'W',
        Gesture.POINTING:    b'B',
        Gesture.SWIPE_LEFT:  b'A',
        Gesture.SWIPE_RIGHT: b'A',
        Gesture.NONE:        b'X',
    }

    def __init__(self, port: str, baud: int = 9600):
        self._serial = None
        self._last: Optional[bytes] = None
        if not SERIAL_AVAILABLE:
            print("[WARN] pyserial not available — Arduino disabled.")
            return
        try:
            self._serial = serial.Serial(port, baud, timeout=0.1)
            time.sleep(2)  # Allow Arduino to reset
            print(f"[ARDUINO] Connected on {port} @ {baud} baud")
        except Exception as e:
            print(f"[WARN] Arduino connection failed: {e}")

    def send(self, gesture: Gesture):
        if self._serial is None:
            return
        cmd = self.COMMANDS.get(gesture, b'X')
        if cmd != self._last:
            try:
                self._serial.write(cmd)
                self._last = cmd
            except Exception as e:
                print(f"[ARDUINO] Write error: {e}")

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.write(b'X')
            self._serial.close()


# ═══════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════

class GestureFXApp:
    """Main application — wires together all subsystems."""

    def __init__(self, args):
        # MediaPipe setup
        self.mp_hands    = mp.solutions.hands
        self.mp_drawing  = mp.solutions.drawing_utils
        self.mp_styles   = mp.solutions.drawing_styles

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.6,
        )

        # Webcam
        self.cap = cv2.VideoCapture(args.camera)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 60)

        # Subsystems
        self.classifier = GestureClassifier()
        self.fire_sys   = FireSystem()
        self.water_sys  = WaterSystem()
        self.beam_sys   = BeamSystem()
        self.wind_sys   = WindSystem()

        self.sound   = SoundManager(args.sound_dir) if not args.no_sound else None
        self.arduino = ArduinoController(args.arduino) if args.arduino else None

        # State
        self.current_gesture = Gesture.NONE
        self.prev_time       = time.time()
        self.fps_smooth      = 30.0
        self.mirror          = not args.no_mirror

    # ── Effect dispatch ──────────────────────────────────────────────

    def _dispatch_effects(self, gesture: Gesture, meta: dict, w: int, h: int):
        wrist     = meta["wrist"]
        fingertips = meta["fingertips"]
        velocity  = meta["velocity"]
        idx_dir   = meta["index_direction"]

        if gesture == Gesture.FIST:
            self.fire_sys.emit(*wrist, intensity=1.2)

        elif gesture == Gesture.OPEN_PALM:
            # Spawn water from each fingertip
            for tip in fingertips[1:]:  # skip thumb
                self.water_sys.emit(*tip, intensity=0.9)

        elif gesture == Gesture.POINTING:
            tip = fingertips[1]  # index fingertip
            self.beam_sys.emit(tip[0], tip[1], idx_dir[0], idx_dir[1], w, h)

        elif gesture in (Gesture.SWIPE_LEFT, Gesture.SWIPE_RIGHT):
            direction = 1 if gesture == Gesture.SWIPE_RIGHT else -1
            speed_mag = min(abs(velocity[0]) / 400.0, 2.0)
            self.wind_sys.emit(*wrist, direction=direction, intensity=speed_mag)

        elif gesture == Gesture.PEACE:
            # Small sparkles from both fingertips as bonus
            for tip in fingertips[1:3]:
                for _ in range(3):
                    angle = random.uniform(0, 2 * math.pi)
                    vx = math.cos(angle) * random.uniform(30, 100)
                    vy = math.sin(angle) * random.uniform(30, 100)
                    color = (random.randint(100, 255),) * 3
                    self.wind_sys.particles.append(
                        Particle(tip[0], tip[1], vx, vy, 1.0, 0.6,
                                 random.uniform(2, 5), color)
                    )

    # ── Main loop ────────────────────────────────────────────────────

    def run(self):
        print("\n[INFO] GestureFX running. Press Q to quit.\n")

        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("[ERR] Cannot read from camera.")
                break

            if self.mirror:
                frame = cv2.flip(frame, 1)

            h, w = frame.shape[:2]

            # ── Timing ──────────────────────────────────────────────
            now = time.time()
            dt  = min(now - self.prev_time, 0.05)   # cap dt to avoid physics explosion
            self.prev_time = now
            self.fps_smooth = 0.9 * self.fps_smooth + 0.1 * (1.0 / (dt + 1e-6))

            # ── Hand detection ───────────────────────────────────────
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = self.hands.process(rgb)
            rgb.flags.writeable = True

            gesture = Gesture.NONE
            meta    = {}

            if results.multi_hand_landmarks:
                hand_lm = results.multi_hand_landmarks[0]

                # Draw skeleton
                self.mp_drawing.draw_landmarks(
                    frame, hand_lm, self.mp_hands.HAND_CONNECTIONS,
                    self.mp_styles.get_default_hand_landmarks_style(),
                    self.mp_styles.get_default_hand_connections_style(),
                )

                gesture, meta = self.classifier.classify(hand_lm, w, h)

                # Dispatch particle effects
                if meta:
                    self._dispatch_effects(gesture, meta, w, h)

            # ── Update particles ─────────────────────────────────────
            self.fire_sys.update(dt)
            self.water_sys.update(dt)
            self.beam_sys.update(dt)
            self.wind_sys.update(dt)

            # ── Render particles ─────────────────────────────────────
            self.wind_sys.draw(frame)
            self.fire_sys.draw(frame)
            self.water_sys.draw(frame)
            self.beam_sys.draw(frame)

            # ── Side effects (audio / hardware) ──────────────────────
            if gesture != self.current_gesture:
                self.current_gesture = gesture
                if self.sound:
                    self.sound.play(gesture)
                if self.arduino:
                    self.arduino.send(gesture)

            # ── HUD ──────────────────────────────────────────────────
            draw_hud(frame, gesture, self.fps_smooth)

            cv2.imshow("GestureFX", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
            elif key == ord('m'):
                self.mirror = not self.mirror
            elif key == ord('c'):
                for sys in [self.fire_sys, self.water_sys, self.wind_sys]:
                    sys.clear()
                self.beam_sys.clear()

        self._cleanup()

    def _cleanup(self):
        self.cap.release()
        cv2.destroyAllWindows()
        self.hands.close()
        if self.arduino:
            self.arduino.close()
        if self.sound and SOUND_AVAILABLE:
            pygame.mixer.quit()
        print("[INFO] GestureFX exited cleanly.")


# ═══════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="GestureFX — Real-Time Hand Gesture Effects")
    p.add_argument("--camera",    type=int,   default=0,       help="Camera index (default: 0)")
    p.add_argument("--no-mirror", action="store_true",         help="Disable mirror flip")
    p.add_argument("--no-sound",  action="store_true",         help="Disable audio")
    p.add_argument("--arduino",   type=str,   default=None,    help="Arduino serial port (e.g. /dev/ttyUSB0 or COM3)")
    p.add_argument("--sound-dir", type=str,   default="sounds",help="Directory with .wav sound files")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app  = GestureFXApp(args)
    app.run()
