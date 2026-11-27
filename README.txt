PATHWISE AI - ENHANCED SMARTTROLLEY PROTOTYPE
============================================

This package keeps the existing SmartTrolley motor control, QR navigation,
voice output, camera reconnection, and shopping workflow. It adds a PathWise
AI section for supermarket accessibility:
- AI image analysis using Ultralytics YOLOv8n (first run downloads yolov8n.pt)
- Use an uploaded aisle image or latest trolley camera frame
- Local SQLite community reports
- Zone-based accessibility report dashboard
- Simple demo route comparison using high-impact reports

IMPORTANT LIMITATIONS
---------------------
1. The bundled pretrained YOLOv8n model is a general COCO object detector.
   It can detect common objects, but it is NOT trained to determine whether
   an aisle is accessible, whether a passage is wide enough, floor damage,
   missing ramps, or safe clearance. Treat results as observations requiring
   human verification. Do not claim certified accessibility assessment.
2. The route map is a small illustrative supermarket graph. Replace it with
   the actual supermarket layout and verified QR-zone locations before use.
3. This is a controlled demonstration prototype, not a certified assistive
   device. A blind shopper should not rely on it as their sole navigation aid.
   Keep a sighted supervisor present during testing; do not test autonomous
   movement in a live supermarket or among shoppers.
4. The ESP32 firmware has a 1-second command timeout and stops motors if
   commands stop. Keep the existing DRY RUN enabled during software testing.

INSTALL (Windows)
-----------------
1. Install Python 3.10 or 3.11.
2. Open Command Prompt in this folder.
3. Run:  py -m venv .venv
4. Run:  .venv\\Scripts\\activate
5. Run:  python -m pip install --upgrade pip
6. Run:  pip install -r requirements.txt
7. Run:  streamlit run smart_trolley_app.py

CAMERA / ESP32
--------------
- Join the phone camera hotspot/network as in your existing setup.
- Set the phone IP Webcam URL in the sidebar (existing default is
  http://192.168.4.3:8080/video).
- ESP32 AP from the supplied sketch: SSID SmartTrolley, password Trolley123,
  IP 192.168.4.1. Use only on your isolated demo setup.
- The dashboard starts in DRY RUN. Do not disable DRY RUN until wheels are
  raised/secured and motor operation is tested under teacher supervision.

FILES
-----
smart_trolley_app.py       Original SmartTrolley application + integration
pathwise_features.py       PathWise AI image scan, reports, map and routes
smarttrolley_esp32.ino     Supplied ESP32 Wi-Fi motor firmware
settings.json              Existing camera and ESP32 settings
calibration.json           Existing QR distance calibration
requirements.txt           Python dependencies

DATABASE
--------
Community and AI observation logs are stored locally in pathwise_reports.db
in the folder where Streamlit is launched. Delete that file only if you want
an empty demo database.
