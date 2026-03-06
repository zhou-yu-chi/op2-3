import os, json, cv2, torch, threading, time, traceback
import numpy as np
from datetime import datetime, timedelta # ⭐️ ADDED timedelta
import shutil # ⭐️ ADDED
from PIL import Image # ⭐️ ADDED
from typing import Tuple

# 請確保這些模組在您的環境中存在
from plc_socket import plc_socket
from logger import loginfo 
from torchvision import transforms
from model_setup import get_model
# from inference import predict_image # ⭐️ REMOVED (using in-memory)
from camera_controller import HuarayCameraController

# =========================
# PLC socket
# =========================
# ⭐️ REMOVED: 全域的 socket_op2 已被移除
# socket_op2 = plc_socket("192.168.162.40", 8501) 

# =========================
# Cameras — IMV SDK indexes
# =========================
cameras = {
    "op2_3": {
        "index": 0,
        "serial": "DA26269AAK00006",
        "base_dir": r"C:\2-3_2-6\OP2-3\KSF-R-30A", # AMC-LS100A #BMC-180A
        "plc_trigger": "DM3350",
        "plc_result": "DM3352",
        "plc_ip": "192.168.162.40", # ⭐️ ADDED
        "plc_port": 8501, # ⭐️ ADDED
        # "socket": socket_op2, # ⭐️ REMOVED
    },
    "op2_6": {
        "index": 3,
        "serial": "DA26269AAK00017",
        "base_dir": r"C:\2-3_2-6\OP2-6\KSF-R-30A", # AMC-LS100A #BMC-180A
        "plc_trigger": "DM6350",
        "plc_result": "DM6352",
        "plc_ip": "192.168.162.40", # ⭐️ ADDED
        "plc_port": 8501, # ⭐️ ADDED
        # "socket": socket_op2, # ⭐️ REMOVED
    },
}

# =========================
# ConvNeXt configs (single crop per station)
# =========================
CLASSIFY_CFG = {
    "op2_3": {
        "model_path": r"C:\Users\功得\Desktop\2-3_2-6\model\1113_2-3_aug.pth",
        "class_names": ["ok", "ng"],
        "crop_ratio": 0.5,
        "dx": 0, "dy": 35,
    },
    "op2_6": {
        "model_path": r"C:\Users\功得\Desktop\2-3_2-6\model\1114_2-6_aug.pth",
        "class_names": ["ok", "ng"],
        "crop_ratio": 0.4,
        "dx": 0, "dy": 180,
    },
}

VAL_TRANSFORM = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
])

# =========================
# Load models once per unique path
# =========================
_MODEL_CACHE = {}
for cam, cfg in CLASSIFY_CFG.items():
    path = cfg["model_path"]; names = cfg["class_names"]
    try:
        model = get_model(num_classes=len(names))
        state = torch.load(path, map_location="cuda:0" if torch.cuda.is_available() else "cpu")
        model.load_state_dict(state)
        model.eval()
        _MODEL_CACHE[path] = model
        loginfo("ConvNeXtInit", f"[{cam}] Loaded model: {path}")
    except Exception as e:
        loginfo("ConvNeXtInit", f"[{cam}] FAILED to load {path}: {e}")

# =========================
# Helpers
# =========================

def cleanup_old_folders(base_dir, days_to_keep):
    """⭐️ ADDED: 刪除超過指定天數的舊資料夾 (格式 YYYY-MM-DD)"""
    if not os.path.exists(base_dir):
        return
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        for folder_name in os.listdir(base_dir):
            folder_path = os.path.join(base_dir, folder_name)
            if os.path.isdir(folder_path):
                try:
                    folder_date = datetime.strptime(folder_name, '%Y-%m-%d')
                    if folder_date.date() < cutoff_date.date():
                        shutil.rmtree(folder_path)
                        loginfo("Cleanup", f"[{os.path.basename(base_dir)}] 已刪除舊資料夾: {folder_path}")
                except ValueError:
                    pass # 忽略非日期格式資料夾 (e.g., "temp", "image_data")
                except Exception as e:
                    loginfo("Cleanup", f"刪除 {folder_path} 時出錯: {e}")
    except Exception as e:
        loginfo("Cleanup", f"清理程序 {base_dir} 出錯: {e}")


def ensure_dirs(base_dir: str) -> Tuple[str, str]:
    """
    Ensure base_dir/YYYY-MM-DD exist.
    """
    date_dir = datetime.now().strftime("%Y-%m-%d")
    full_dir = os.path.join(base_dir, date_dir)
    os.makedirs(full_dir, exist_ok=True) 
    return date_dir, full_dir

def _imwrite_png(path: str, img: np.ndarray) -> bool:
    if img is None or img.size == 0:
        return False
    # ⭐️ NEW: 確保儲存前目錄存在
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception as e:
        print(f"❌ _imwrite_png makedirs failed: {e}")
        return False
        
    img = np.ascontiguousarray(img)
    ok = cv2.imwrite(path, img)
    if not ok:
        print(f"❌ imwrite failed → {path} (shape={None if img is None else img.shape}, dtype={None if img is None else img.dtype})")
    return ok

def save_full_frame(image_bgr: np.ndarray, base_dir: str, date_dir: str, base_name: str) -> Tuple[bool, str]:
    path = os.path.join(base_dir, date_dir, f"{base_name}.png")
    ok = _imwrite_png(path, image_bgr)
    return ok, path

def _center_shift_crop(img_bgr: np.ndarray, crop_ratio: float, dx: int, dy: int) -> np.ndarray:
    """Crop a window centered at (cx+dx, cy+dy). Bounds-safe."""
    h, w = img_bgr.shape[:2]
    cw, ch = max(1, int(w * crop_ratio)), max(1, int(h * crop_ratio))
    cx, cy = w // 2 + int(dx), h // 2 + int(dy)
    x1 = max(0, cx - cw // 2)
    y1 = max(0, cy - ch // 2)
    x2 = min(w, x1 + cw)
    y2 = min(h, y1 + ch)
    x1 = max(0, x2 - cw)
    y1 = max(0, y2 - ch)
    return img_bgr[y1:y2, x1:x2]

# ⭐️ REMOVED: def _predict_path_safe(...)

def _predict_in_memory(cv2_img_bgr: np.ndarray, model, class_names, transform) -> str:
    """⭐️ ADDED: 在內存中直接預測 (CV2 BGR -> PIL -> Tensor -> Pred)"""
    try:
        img_rgb = cv2.cvtColor(cv2_img_bgr, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(img_rgb)
        input_tensor = transform(pil_image)
        input_batch = input_tensor.unsqueeze(0)
        device = next(model.parameters()).device
        input_batch = input_batch.to(device)

        with torch.no_grad():
            output = model(input_batch)
            _, preds = torch.max(output, 1)
            pred_class = class_names[preds[0]]
        return pred_class
    except Exception as e:
        loginfo("ConvNeXt", f"_predict_in_memory failed: {e}")
        return "unknown"


# ================================================================
# ⭐️⭐️⭐️ 函式 classify_frame 已根據您的最新需求修改 ⭐️⭐️⭐️
# ================================================================
def classify_frame(camera_name, image_bgr, base_dir, date_dir, base_name):
    """
    ⭐️ MODIFIED (2025-10-29): 
    - 儲存 OK/NG 原始裁切畫面 (無文字)。
    - 儲存路徑不包含日期: [base_dir]/image_data/[OK/NG]/[filename].png
    """
    cfg = CLASSIFY_CFG.get(camera_name)
    if not cfg:
        return None, None
    model = _MODEL_CACHE.get(cfg["model_path"])
    names = cfg["class_names"]
    if model is None or not names:
        loginfo("ConvNeXt", f"[{camera_name}] Model or class names missing.")
        return None, None

    # 1. 進行裁切 (此為您需要的原始影像)
    crop = _center_shift_crop(image_bgr, cfg["crop_ratio"], cfg["dx"], cfg["dy"])
    
    if crop is None or crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        print(f"❌ [{camera_name}] Empty crop! shape={None if crop is None else crop.shape}")
        return {"final": "ng"}, None

    out = {"camera": camera_name, "final": "ng"}
    
    # 2. 執行 in-memory 預測
    pred = _predict_in_memory(crop, model, names, VAL_TRANSFORM)
    out["final"] = pred if pred in ("ok", "ng") else "ng"
    
    # ⭐️ (REMOVED) 刪除 temp 檔案的邏輯

    # ========= 【⭐️ NEW】儲存 "原始" 裁切圖片 (OK/NG 分類) =========
    log_save_path = None # 用於返回給 camera_task 的 NG 路徑
    try:
        # 3. 建立儲存路徑
        save_root = os.path.join(base_dir, "image_data") # e.g., C:\...AMC-LS100A\image_data
        result_folder = out["final"].upper() # "OK" or "NG"
        
        # ⭐️ MODIFIED: 移除 date_dir
        # e.g., ...\image_data\NG
        final_save_dir = os.path.join(save_root, result_folder) 
        
        # 4. 確保目標資料夾存在 (移至 _imwrite_png 內部)
        # os.makedirs(final_save_dir, exist_ok=True) # (已移動)
        
        raw_save_path = os.path.join(final_save_dir, f"{base_name}.png")
        
        # 5. 儲存 "crop" (原始裁切影像, 尚未 putText)
        save_ok = _imwrite_png(raw_save_path, crop) 
        
        if save_ok:
            print(f"💾 Saved raw crop ({result_folder}) → {raw_save_path}")
            # 僅在 NG 時設定此路徑, 用於日誌
            if out["final"] == "ng":
                log_save_path = raw_save_path 
        else:
            print(f"❌ FAILED to save raw crop → {raw_save_path}")
            
    except Exception as e:
        print(f"❌ FAILED to save raw crop: {e}")
        traceback.print_exc()
    # =============================================================

    # ========= 顯示用圖片處理 (帶有文字標註) =========
    # (這部分僅供未來可能的顯示/除錯用, 影像 "不會" 被儲存)
    display_img = crop.copy()
    
    font_scale = 1.8 
    thickness = 4
    text = out["final"].upper()
    color = (0, 0, 255) if text == "NG" else (0, 255, 0)
    
    cv2.putText(display_img, text, (10, 60), 
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)
    
    station_text = "2-3" if camera_name == "op2_3" else "2-6"
    font_scale_st = 1.4
    (text_w, text_h), _ = cv2.getTextSize(station_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale_st, 2)
    cv2.putText(display_img, station_text,
                (display_img.shape[1] - text_w - 20, 60),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale_st, (255, 255, 255), 2)

    # ========= 【⭐️ REMOVED】舊的儲存邏輯 =========
    # (if out["final"] == "ng": ...) 區塊已被移除
    
    # 6. 回傳結果
    # ⭐️ 回傳 log_save_path (NG時有值, OK時為None)
    return out, log_save_path
# ================================================================
# ⭐️⭐️⭐️ 修改結束 ⭐️⭐️⭐️
# ================================================================


def safe_send(sock, addr, val, suffix=".U"):
    """⭐️ MODIFIED: 增加對 sock is None 的檢查"""
    if sock is None:
        print(f"❌ PLC send skipped (socket is None) {addr} <= {val}")
        return
    try:
        sock.Send(addr, val, suffix)
        print(f"📤 PLC {addr} <= {val}")
    except Exception as e:
        print(f"❌ PLC send failed {addr} <= {val}: {e}")
        raise # ⭐️ 拋出異常，讓 camera_task 知道連線已中斷

# =========================
# Connect cameras
# =========================
camera_objects = {}
for name, cfg in cameras.items():
    os.makedirs(cfg["base_dir"], exist_ok=True)
    cam = HuarayCameraController()
    # ⭐️ MODIFIED: ensure_dirs 只需要兩個回傳值
    date_dir, _ = ensure_dirs(cfg["base_dir"])
    if cam.connect(device_index=cfg["index"]):
        camera_objects[name] = cam
        print(f"✅ Camera {name} CONNECTED (Index {cfg['index']}, Serial {cfg['serial']}) → saving to {cfg['base_dir']}\\{date_dir}")
    else:
        print(f"❌ Camera {name} FAILED to connect")

# =========================
# Thread loop
# =========================
def camera_task(cam: HuarayCameraController, plc_trigger, plc_result, name, plc_ip, plc_port, base_dir):
    """⭐️ MODIFIED: 
    - 接收 plc_ip, plc_port (不再接收 sock)
    - 內部管理 socket 連線和重連
    - 內部呼叫 cleanup_old_folders
    """
    socket = None
    last_trig = None

    def _connect_plc():
        """(Re)connects the PLC."""
        print(f"[{name}]  attempting to connect PLC {plc_ip}...")
        try:
            sock = plc_socket(plc_ip, plc_port)
            print(f"[{name}] PLC connected.")
            return sock
        except Exception as e:
            print(f"[{name}] PLC connection failed: {e}")
            return None

    # 啟動時進行第一次連線
    socket = _connect_plc()

    while True:
        # ⭐️ 1. 每次迴圈先執行清理
        # (清理任務很輕，不會影響效能)
        # ⭐️
        # ⭐️ MODIFIED: 清理 "base_dir" 以及 "image_data" 底下的資料夾
        # ⭐️ (image_data 底下雖然不會有日期資料夾, 但以防萬一)
        cleanup_old_folders(base_dir, 5) 
        cleanup_old_folders(os.path.join(base_dir, "image_data"), 5) 

        # ⭐️ 2. 檢查 PLC 連線
        if socket is None:
            print(f"[{name}] PLC disconnected. Retrying in 5s...")
            time.sleep(5)
            socket = _connect_plc()
            continue # 進入下一次迴圈

        # ⭐️ 3. 讀取 PLC 狀態 (帶有重連邏輯)
        try:
            raw = socket.Get(plc_trigger, ".D")
            trig = int(raw.strip().splitlines()[0])
        except Exception as e:
            print(f"❌ [{name}] PLC Get error: {e}. Marking for reconnect.")
            socket = None # ⭐️ 標記為斷線，下次迴圈重連
            continue

        # ⭐️ 4. 檢查觸發 (保持不變)
        if trig != last_trig:
            print(f"[{name}] Trigger={trig}{' → Capturing' if trig == 1 else ' → Waiting'}")
            last_trig = trig

        if trig != 1:
            time.sleep(0.5) # ⭐️ 在等待時 sleep，避免空轉
            continue

        # ⭐️ 5. 主邏輯 (帶有重連邏輯)
        try:
            if not cam.start_grabbing():
                raise RuntimeError("start_grabbing() failed")
            time.sleep(0.1)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"{name}_{ts}"

            frame = cam.grab_image_numpy(timeout_ms=3000)
            cam.stop_grabbing()
            if frame is None:
                raise RuntimeError("No frame")

            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            # ⭐️ MODIFIED: date_dir 仍被建立, 但不再用於 classify_frame 的儲存路徑
            date_dir, _ = ensure_dirs(base_dir)

            # ⭐️ (REMOVED) 移除 save_full_frame

            # ⭐️ (REMOVED) 移除 PLC result=2 
            
            time.sleep(0.3)

            # Classify (with crop)
            # ⭐️ MODIFIED: date_dir 參數仍傳入 (雖然內部沒用), 避免修改 public API
            cls_out, saved_ng_path = classify_frame(name, frame, base_dir, date_dir, base_name)
            
            if cls_out:
                final = cls_out["final"]
                print(f"🧠 [{name}] FINAL={final.upper()}")

                if saved_ng_path:
                    # ⭐️ Log 紀錄的路徑現在是 ...\image_data\NG\...
                    loginfo("CameraTask", f"[{name}] NG Image saved: {saved_ng_path}")

                safe_send(socket, plc_result, 1 if final == "ok" else 3, ".U")
            else:
                print(f"⚠️  [{name}] classification skipped (no config/model)")
                safe_send(socket, plc_result, 3, ".U")

            # Step 5: reset trigger
            time.sleep(0.3)
            safe_send(socket, plc_trigger, 0, ".U")

        except Exception as e:
            # ⭐️ 關鍵：主邏輯（包含 safe_send）出錯，
            # ⭐️ 很有可能是連線問題，同樣標記 socket = None
            print(f"❌ [{name}] MainTask ERROR: {traceback.format_exc()}")
            loginfo("CameraTask", f"[{name}] ERROR: {e}")
            try:
                cam.stop_grabbing()
            except Exception:
                pass
            
            # 嘗試發送錯誤訊號 (如果 socket 剛好在這一刻還沒 None)
            safe_send(socket, plc_result, 3, ".U") 
            safe_send(socket, plc_trigger, 0, ".U")
            
            socket = None # ⭐️ 確保標記為斷線

        print(f"-----------------------------------")


# =========================
# Start threads
# =========================
threads = []

# ⭐️ (REMOVED) 移除 cleanup_thread

for name, cfg in cameras.items():
    cam = camera_objects.get(name)
    if not cam:
        print(f"⏭️  {name} not connected; skipping.")
        continue
    
    # ⭐️ MODIFIED: 更新傳入的參數
    t = threading.Thread(
        target=camera_task,
        args=(
            cam, 
            cfg["plc_trigger"], 
            cfg["plc_result"], 
            name, 
            cfg["plc_ip"],     # ⭐️ NEW
            cfg["plc_port"],   # ⭐️ NEW
            cfg["base_dir"]
        ),
        daemon=True
    )
    t.start()
    threads.append(t)
    print(f"🚀 Started thread for {name}")

for t in threads:
    t.join()