# GestureFX — Setup Guide

## Quick Start

```bash
# 1. Install Python dependencies
pip install opencv-python mediapipe numpy pygame pyserial

# 2. Run (webcam index 0, mirrored, no Arduino)
python gesture_effects.py

# 3. With Arduino on Linux/Mac
python gesture_effects.py --arduino /dev/ttyUSB0

# 4. With Arduino on Windows
python gesture_effects.py --arduino COM3

# 5. All options
python gesture_effects.py --help
```

## Gesture Reference

| Gesture      | Effect        | How to make it                          |
|--------------|---------------|-----------------------------------------|
| Open Palm    | 💧 Water       | All 5 fingers extended, facing camera   |
| Fist         | 🔥 Fire        | All fingers curled into a fist          |
| Pointing     | ⚡ Energy Beam | Only index finger extended              |
| Swipe        | 💨 Wind        | Move hand fast horizontally             |
| Peace ✌      | ✨ Sparkles    | Index + middle only (bonus!)            |

## Keyboard Shortcuts (while running)

| Key | Action             |
|-----|--------------------|
| Q   | Quit               |
| M   | Toggle mirror mode |
| C   | Clear all particles|

## Sound Effects (optional)

Place `.wav` files in a `sounds/` folder next to the script:
- `sounds/fire_loop.wav`
- `sounds/water_loop.wav`
- `sounds/beam_loop.wav`
- `sounds/wind_loop.wav`

Free sources: freesound.org, zapsplat.com

## Arduino Wiring

```
Arduino Pin 9  → MOSFET gate → Red   LED strip
Arduino Pin 10 → MOSFET gate → Green LED strip  
Arduino Pin 11 → MOSFET gate → Blue  LED strip
Arduino Pin 4  → Relay IN    → 12V Fan
Arduino Pin 5  → Relay IN    → Mist sprayer
```

Flash `arduino_controller/arduino_controller.ino` using Arduino IDE.

## Adding New Gestures

1. Add a new value to the `Gesture` enum
2. Add classification logic in `GestureClassifier.classify()`
3. Add particle emission in `GestureFXApp._dispatch_effects()`
4. (Optional) Add Arduino command in `ArduinoController.COMMANDS`
5. (Optional) Add sound file in `SoundManager.SOUNDS`

## Performance Tips

- Use a dedicated GPU if available (OpenCV will auto-use it)
- Lower resolution: `--camera 0` then edit `CAP_PROP_FRAME_WIDTH` to 640
- Reduce `max_num_hands=1` (already default)
- Close other applications to free CPU cores

## Requirements

- Python 3.8+
- Webcam (720p or higher recommended)
- macOS / Linux / Windows 10+
- Arduino Uno/Nano (optional)
