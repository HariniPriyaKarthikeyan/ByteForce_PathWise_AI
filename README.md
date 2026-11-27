# ByteForce_PathWise_AI

# SmartTrolley AI – Voice-Guided Accessible Shopping Assistant

**Team:** ByteForce  
**Live Demo:** https://byteforcepathwiseai-lhcjgao9gms4ainic2hwfl.streamlit.app/  
**GitHub:** https://github.com/HariniPriyaKarthikeyan/ByteForce_PathWise_AI

## 1. About the Project

SmartTrolley AI is an AI-assisted shopping prototype designed to support visually impaired shoppers in supermarket environments.

The system combines voice commands, QR-code detection, computer vision, shortest-path navigation and wireless hardware control to demonstrate how technology can improve accessibility and make shopping more convenient.

Users can select products, receive spoken navigation instructions and monitor the trolley through a live camera feed.

The project also integrates PathWise AI, an accessibility add-on that explores AI-assisted aisle analysis and community accessibility reporting.

## 2. Key Features

### Voice-Controlled Navigation
- Accepts typed and spoken commands.
- Provides spoken navigation instructions.
- Supports commands such as start, stop, repeat and product selection.
- Uses text-to-speech for user guidance.

### QR Code Detection
- Detects QR codes using OpenCV.
- Supports additional QR decoding through Pyzbar.
- Remembers recent QR detections.
- Estimates distance using camera calibration.

### Shortest-Path Navigation
- Uses Dijkstra's algorithm to calculate routes.
- Supports supermarket locations such as Entrance, Junction, Milk, Bread and Rice.
- Calculates navigation paths based on the selected products.

### Live Camera Monitoring
- Connects to a smartphone camera using IP Webcam.
- Supports MJPEG video streaming.
- Automatically switches to snapshot mode when necessary.
- Provides camera reconnection and testing features.

### ESP32 Hardware Integration
- Communicates wirelessly with an ESP32.
- Supports forward, backward, left, right and stop commands.
- Includes motor connection diagnostics.
- Provides pulse-based movement and continuous movement modes.

### PathWise AI Integration
- AI-assisted aisle image analysis.
- YOLOv8 object detection.
- Accessibility issue reporting.
- Local SQLite-based report storage.

### Safety Features
- Starts in DRY RUN mode.
- Provides a simulation mode that does not operate physical motors.
- Includes an emergency stop.
- Stops navigation when checkpoints cannot be detected.

## 3. Technologies Used

| Technology and  Purpose |

| Python | Main programming language |
| Streamlit | Web application interface |
| OpenCV | Camera processing and QR detection |
| NumPy | Image processing |
| Requests | Wireless ESP32 communication |
| ESP32 | Hardware controller |
| Arduino IDE | ESP32 programming |
| Dijkstra's Algorithm | Shortest-path calculation |
| Pyzbar | Additional QR decoding |
| pyttsx3 / System Speech Engine | Text-to-speech |
| SpeechRecognition | Voice command recognition |
| YOLOv8 | AI object detection |
| SQLite | Accessibility report storage |
| JSON | Settings and calibration storage |

## System Architecture

1. The user selects products or provides a voice command.
2. The application calculates the shortest route using Dijkstra's algorithm.
3. The smartphone camera captures the surrounding QR checkpoints.
4. OpenCV detects and decodes the QR codes.
5. The application estimates the distance using camera calibration.
6. Navigation instructions are communicated through text-to-speech.
7. The ESP32 receives movement commands in hardware mode.
8. The PathWise AI module provides additional accessibility analysis and reporting.

## Supermarket Navigation Map

The prototype currently supports five locations:

- ENTRANCE
- JUNCTION
- MILK
- BREAD
- RICE

The navigation graph connects the entrance to the junction and the junction to the three product locations.

Dijkstra's algorithm determines the shortest available route between locations.

## Installation and Setup

### Prerequisites
- Python 3.10 or compatible version
- Arduino IDE
- ESP32 development board
- Smartphone with IP Webcam
- Laptop and required hardware components

### Step 1: Clone the repository

```bash
git clone https://github.com/HariniPriyaKarthikeyan/ByteForce_PathWise_AI.git
cd ByteForce_PathWise_AI
```

### Step 2: Install dependencies

```bash
pip install -U streamlit opencv-python numpy requests
```

Optional packages:

```bash
pip install pyzbar SpeechRecognition pyttsx3
```

For Linux audio support:

```bash
sudo apt install espeak-ng ffmpeg
```

### Step 3: Run the application

```bash
streamlit run smart_trolley_app.py
```

### Step 4: Configure the camera

1. Install and open IP Webcam on your smartphone.
2. Start the camera server.
3. Connect the laptop to the same Wi-Fi network or hotspot.
4. Enter the camera URL displayed by the smartphone application.
5. Use the Test Camera option to check the connection.

### Step 5: Configure ESP32

1. Connect the ESP32 to the laptop for programming.
2. Upload the corresponding firmware using Arduino IDE.
3. Connect the laptop to the ESP32's configured Wi-Fi network.
4. Enter the ESP32 IP address in the application.
5. Test the connection while DRY RUN is enabled.

## Safety and Limitations

- The application starts in DRY RUN mode.
- Simulation mode never operates physical motors.
- QR-based positioning depends on correctly placed and readable checkpoints.
- Distance measurements depend on camera calibration.
- Camera availability depends on network connectivity.
- Object detection does not guarantee that every obstacle will be identified.
- The supermarket map is a simplified prototype layout.

**SmartTrolley AI is an educational demonstration prototype, not a certified mobility aid. It should not be used as a replacement for a white cane, guide dog or human assistance.**

## Future Improvements

- Improve obstacle detection and recognition.
- Expand supermarket mapping.
- Add multilingual voice assistance.
- Improve indoor positioning accuracy.
- Integrate more advanced AI-based product recognition.
- Conduct supervised usability testing with accessibility experts and intended users.
