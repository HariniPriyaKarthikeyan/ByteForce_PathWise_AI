"""PathWise AI add-on: image-based aisle checks and community reports.
Optional dependency: ultralytics. Detection is advisory, not a safety guarantee.
"""
import os, sqlite3, time
from datetime import datetime
import cv2
import numpy as np
import streamlit as st

DB_PATH = "pathwise_reports.db"

@st.cache_resource
def pathwise_model():
    try:
        from ultralytics import YOLO
        return YOLO("yolov8n.pt"), None
    except Exception as exc:
        return None, f"YOLO unavailable: {exc}"

def db_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, zone TEXT,
        category TEXT, description TEXT, severity TEXT, source TEXT)""")
    con.commit()
    return con

def save_report(zone, category, description, severity, source="Community"):
    con = db_conn()
    con.execute("INSERT INTO reports(created_at,zone,category,description,severity,source) VALUES(?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), zone, category, description, severity, source))
    con.commit(); con.close()

def read_reports():
    con = db_conn()
    rows = con.execute("SELECT created_at,zone,category,description,severity,source FROM reports ORDER BY id DESC").fetchall()
    con.close(); return rows

def run_detection(image_bytes):
    model, err = pathwise_model()
    if model is None:
        return None, [], err
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None: return None, [], "Could not decode image."
    result = model.predict(img, conf=0.35, verbose=False)[0]
    names = model.names
    detections = []
    for box in result.boxes:
        cls_id = int(box.cls[0]); label = str(names.get(cls_id, cls_id))
        conf = float(box.conf[0])
        detections.append({"label": label, "confidence": conf})
        x1,y1,x2,y2 = map(int, box.xyxy[0].tolist())
        cv2.rectangle(img,(x1,y1),(x2,y2),(40,190,80),2)
        cv2.putText(img,f"{label} {conf:.2f}",(x1,max(20,y1-7)),cv2.FONT_HERSHEY_SIMPLEX,.55,(40,190,80),2)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB), detections, None

def pathwise_panel(T):
    st.divider()
    st.header("♿ PathWise AI · Supermarket Accessibility")
    st.caption("Accessibility assistance for blind and visually impaired shoppers. AI detections are advisory and must be verified.")
    tabs = st.tabs(["AI aisle scan", "Community reports", "Accessibility map", "Route planner"])
    with tabs[0]:
        st.subheader("Analyse a supermarket aisle")
        source = st.radio("Image source", ["Upload aisle image", "Use current trolley camera frame"], horizontal=True)
        data = None
        if source == "Upload aisle image":
            up = st.file_uploader("Upload a JPG or PNG aisle image", type=["jpg","jpeg","png"], key="pw_upload")
            if up: data = up.getvalue()
        else:
            if getattr(T, "frame_jpeg", None):
                data = T.frame_jpeg
                st.image(data, caption="Latest trolley camera frame")
            else: st.warning("No camera frame available. Connect the camera or upload an image.")
        zone = st.selectbox("Supermarket zone", ["ENTRANCE","JUNCTION","MILK","BREAD","RICE","CHECKOUT","OTHER"], key="pw_scan_zone")
        if st.button("🔎 Analyse aisle image", type="primary", disabled=data is None):
            with st.spinner("Running computer-vision analysis…"):
                annotated, detections, error = run_detection(data)
            if error: st.error(error)
            else:
                st.image(annotated, caption="AI annotations — review before acting")
                if detections:
                    st.dataframe([{"Detected object":d["label"],"Confidence":f"{d['confidence']:.0%}"} for d in detections], use_container_width=True)
                    st.info("The pretrained model recognises general objects. It does not reliably classify aisle blockage, floor damage, ramp access or whether a route is passable.")
                    # Only objects that may be relevant are saved as observations; user confirms category.
                    save_report(zone, "AI observation", ", ".join(sorted(set(d['label'] for d in detections))), "Needs verification", "AI")
                    st.success("AI observation saved to the accessibility log for verification.")
                else: st.info("No objects were detected at the selected confidence threshold. This does not prove the aisle is clear.")
    with tabs[1]:
        st.subheader("Submit a community accessibility report")
        with st.form("pw_report_form", clear_on_submit=True):
            zone = st.selectbox("Location / aisle", ["ENTRANCE","JUNCTION","MILK","BREAD","RICE","CHECKOUT","OTHER"])
            category = st.selectbox("Barrier type", ["Blocked aisle","Cart or trolley obstruction","Boxes / misplaced products","Spill / floor obstruction","Narrow passage","Missing ramp / step access","Damaged floor","Other"])
            description = st.text_area("Describe what is happening")
            severity = st.selectbox("Impact", ["Low","Medium","High"])
            submitted = st.form_submit_button("Submit report")
        if submitted:
            if not description.strip(): st.warning("Please add a short description.")
            else:
                save_report(zone, category, description.strip(), severity)
                st.success("Report added to the accessibility log.")
        st.caption("Reports are stored locally in pathwise_reports.db on this computer.")
    with tabs[2]:
        st.subheader("Supermarket accessibility status")
        rows = read_reports()
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows, columns=["Time","Zone","Category","Description","Impact","Source"])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.bar_chart(df.groupby("Zone").size())
        else: st.info("No accessibility reports yet. Submit a report or run an aisle scan.")
        st.caption("This is a zone-based prototype map/log, not a live GPS map. QR markers associate the trolley with known zones.")
        st.markdown("**Demo zone layout**")
        st.code("ENTRANCE ── JUNCTION ── CHECKOUT\n                ├── MILK\n                ├── BREAD\n                └── RICE")
    with tabs[3]:
        st.subheader("Compare known routes")
        st.caption("Prototype route comparison uses manually configured supermarket zones and reported barriers. It does not autonomously steer around people.")
        reports = read_reports()
        blocked = {r[1] for r in reports if r[4] == "High" and r[5] == "Community"}
        options = ["ENTRANCE","JUNCTION","MILK","BREAD","RICE","CHECKOUT"]
        start = st.selectbox("Start", options, index=0)
        goal = st.selectbox("Destination", options, index=2)
        if st.button("Compare route"):
            # Demo graph; route edges represent aisle connections. A high-impact community report
            # flags a zone for review rather than claiming the zone is physically impassable.
            graph = {"ENTRANCE":["JUNCTION"],"JUNCTION":["ENTRANCE","MILK","BREAD","RICE","CHECKOUT"],
                     "MILK":["JUNCTION"],"BREAD":["JUNCTION"],"RICE":["JUNCTION"],"CHECKOUT":["JUNCTION"]}
            from collections import deque
            q=deque([(start,[start])]); seen={start}; route=None
            while q:
                node,path=q.popleft()
                if node==goal: route=path; break
                for nxt in graph.get(node,[]):
                    if nxt not in seen: seen.add(nxt); q.append((nxt,path+[nxt]))
            if route:
                flagged=[z for z in route if z in blocked]
                st.write(" → ".join(route))
                if flagged: st.warning("High-impact reports exist in: "+", ".join(flagged)+". Verify these zones and ask staff for assistance.")
                else: st.success("No high-impact community reports are recorded along this demo route. This is not a guarantee of accessibility.")
            else: st.warning("No route found in the demo map.")
