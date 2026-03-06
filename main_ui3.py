import sys
import os
import json
import shutil
import traceback
import zipfile
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QSlider, QFileDialog, QMessageBox, QGroupBox, QLineEdit,
                             QDialog, QDateEdit, QFormLayout, QDialogButtonBox, QProgressDialog)
from PySide6.QtCore import Qt, QDate

# ==========================================
# 🔧 1. 路徑設定 (依照你的 OP3 專案修改)
# ==========================================
MODEL_BASE_DIR = r"C:\3-1_3-3\model"
CONFIG_FILE = r"S22009--Conquer-Fuse-Assembly-Automation-OP3\config.json"  # 放在同層目錄即可

# 圖片根目錄 (參照 op3_save_images.py)
IMG_ROOT_OP3_1 = r"C:\G_D_2\S22009--Conquer-Fuse-Assembly-Automation-OP3\picture"
IMG_ROOT_OP3_3 = r"C:\3-1_3-3\OP3-3_pictures"

class DateRangeDialog(QDialog):
    """ 彈出式視窗：選擇日期範圍 """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("選擇匯出日期範圍")
        self.resize(450, 250) 

        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #ffffff; font-family: 'Microsoft JhengHei UI', sans-serif; }
            QDateEdit { background-color: #3c3f41; color: #e0e0e0; border: 2px solid #555; border-radius: 5px; padding: 5px 10px; font-size: 18px; min-height: 35px; }
            QDateEdit:hover { border: 2px solid #4db6ac; }
            QDateEdit::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 40px; border-left-width: 1px; border-left-color: #555; border-left-style: solid; background-color: #333; }
            QDateEdit::down-arrow { width: 16px; height: 16px; image: none; border: 2px solid #aaa; border-top: 0; border-right: 0; transform: rotate(-45deg); margin-top: -3px; }
            QCalendarWidget QWidget { alternate-background-color: #444; }
            QCalendarWidget QAbstractItemView { background-color: #2b2b2b; color: white; font-size: 16px; selection-background-color: #4db6ac; selection-color: black; }
            QCalendarWidget QWidget#qt_calendar_navigationbar { background-color: #2b2b2b; min-height: 40px; }
            QCalendarWidget QToolButton { color: white; font-weight: bold; icon-size: 24px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(25)
        layout.setContentsMargins(40, 40, 40, 40)

        form = QFormLayout()
        form.setVerticalSpacing(20)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        today = QDate.currentDate()

        self.start_date = QDateEdit()
        self.start_date.setDate(today)
        self.start_date.setCalendarPopup(True) 
        self.start_date.setDisplayFormat("yyyy-MM-dd")

        self.end_date = QDateEdit()
        self.end_date.setDate(today)
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")

        lbl_start = QLabel(" 開始日期 :")
        lbl_start.setStyleSheet("font-size: 16px; font-weight: bold;")
        lbl_end = QLabel(" 結束日期 :")
        lbl_end.setStyleSheet("font-size: 16px; font-weight: bold;")

        form.addRow(lbl_start, self.start_date)
        form.addRow(lbl_end, self.end_date)
        
        layout.addLayout(form)
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("匯出")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        
        buttons.setStyleSheet("QPushButton { background-color: #0277bd; color: white; border-radius: 5px; padding: 8px 20px; font-size: 16px; font-weight: bold; min-width: 80px; } QPushButton:hover { background-color: #0288d1; }")
        
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def get_dates(self):
        return self.start_date.date().toPython(), self.end_date.date().toPython()


class SettingsEditor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OP3 AOI 參數設定工具") 
        self.resize(650, 550)

        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #ffffff; font-family: 'Microsoft JhengHei UI'; font-size: 14px; }
            QGroupBox { border: 1px solid #555; border-radius: 8px; margin-top: 10px; font-weight: bold; color: #ddd; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; }
            QPushButton { background-color: #0277bd; color: white; border-radius: 4px; font-weight: bold; padding: 8px; }
            QPushButton:hover { background-color: #0288d1; }
            QLineEdit { background-color: #444; color: #ccc; border: 1px solid #555; border-radius: 4px; padding: 5px; }
        """)
        
        if not os.path.exists(MODEL_BASE_DIR):
            os.makedirs(MODEL_BASE_DIR, exist_ok=True)
        
        self.config = self.load_config()
        self.init_ui()

    def load_config(self):
        print("[Log] 正在讀取設定檔...")
        
        # ★ 修正 1：預設值改為符合 OP3 的 JSON 巢狀結構
        config = {
            "confidence_threshold": 0.80, 
            "models": {
                "op3_1": "",
                "op3_3": ""
            }
        }
        
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved_data = json.load(f)
                    
                    # 確保讀取舊檔時不會覆蓋掉預設的 dict 結構
                    if "models" in saved_data:
                        config["models"].update(saved_data["models"])
                    
                    config["confidence_threshold"] = saved_data.get("confidence_threshold", config["confidence_threshold"])
                    
                    print(f"[Success] 設定檔讀取成功: {config}")
            except Exception as e:
                print(f"❌ 設定檔讀取失敗 (將使用預設值): {e}")
        else:
            print(f"[Warning] 找不到設定檔 {CONFIG_FILE}，將使用預設值。")
            
        return config

    def save_config(self):
        try:
            final_data = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        final_data = json.load(f)
                except:
                    pass
            
            # ★ 修正：確保寫入時 models 的結構能正確合併
            final_data["confidence_threshold"] = self.config["confidence_threshold"]
            
            if "models" not in final_data:
                final_data["models"] = {}
            final_data["models"].update(self.config.get("models", {}))

            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_data, f, indent=4, ensure_ascii=False)
            
            QMessageBox.information(self, "成功", "✅ 設定已儲存！\n請重新啟動 AOI 主程式以生效。")
            
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"儲存失敗: {e}")

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("🛠️ OP3-1 / OP3-3 系統參數設定")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #4db6ac;")
        layout.addWidget(title)
        
        path_info = QLabel(f"🔒 模型存放位置: {MODEL_BASE_DIR}")
        path_info.setStyleSheet("color: #777; font-size: 12px; margin-bottom: 10px;")
        layout.addWidget(path_info)

        # --- 1. 信心度設定 ---
        group_conf = QGroupBox("信心度門檻 (Confidence)")
        group_layout = QVBoxLayout(group_conf)
        h_slider_layout = QHBoxLayout()
        
        current_conf = self.config.get("confidence_threshold", 0.8)
        
        self.lbl_conf = QLabel(f"{int(current_conf*100)}%")
        self.lbl_conf.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffeb3b; min-width: 60px; qproperty-alignment: AlignCenter;")
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(50, 99)
        self.slider.setValue(int(current_conf*100))
        self.slider.valueChanged.connect(lambda v: (
            self.lbl_conf.setText(f"{v}%"), 
            self.config.update({"confidence_threshold": v/100.0})
        ))
        
        h_slider_layout.addWidget(self.slider) 
        h_slider_layout.addWidget(self.lbl_conf)
        group_layout.addLayout(h_slider_layout)

        lbl_tips = QLabel("💡 說明：若 AI 的把握度低於此設定值，系統將強制判定為 NG。")
        lbl_tips.setStyleSheet("color: #aaa; font-size: 12px; margin-top: 5px;")
        group_layout.addWidget(lbl_tips)
        layout.addWidget(group_conf)

        # --- 2. 模型選擇與圖片匯出 ---
        group_model = QGroupBox("模型檔案管理 & 圖片匯出")
        model_layout = QVBoxLayout(group_model)

        # 針對 OP3-1 建立欄位
        self.create_row(model_layout, "OP3-1 相機", "op3_1", img_root=IMG_ROOT_OP3_1)
        
        # 針對 OP3-3 建立欄位
        self.create_row(model_layout, "OP3-3 相機", "op3_3", img_root=IMG_ROOT_OP3_3)
        
        layout.addWidget(group_model)

        # --- 3. 儲存按鈕 ---
        layout.addStretch()
        btn_save = QPushButton("💾 儲存設定 (Save Config)")
        btn_save.setStyleSheet("background-color: #2e7d32; font-size: 16px; height: 40px;")
        btn_save.clicked.connect(self.save_config)
        layout.addWidget(btn_save)

        self.setLayout(layout)

    def create_row(self, layout, label_text, model_key, img_root):
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #4db6ac; margin-top: 5px;")
        layout.addWidget(lbl)
        
        h_layout = QHBoxLayout()
        
        line_edit = QLineEdit()
        current_model = self.config.get("models", {}).get(model_key, "")
        line_edit.setText(current_model)
        line_edit.setReadOnly(True)
        line_edit.setPlaceholderText("尚未設定模型...")
        
        btn_import = QPushButton("📂 匯入模型")
        btn_import.clicked.connect(lambda: self.import_model(model_key, line_edit))
        
        btn_export = QPushButton("📤 匯出圖片")
        btn_export.setStyleSheet("background-color: #d84315;")
        btn_export.clicked.connect(lambda: self.export_images(img_root, label_text))
        
        h_layout.addWidget(line_edit)
        h_layout.addWidget(btn_import)
        h_layout.addWidget(btn_export)
        
        layout.addLayout(h_layout)

    def import_model(self, config_key, line_edit):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "選擇新模型檔案",       
            "",                   
            "Model Files (*.pth)" 
        )
        
        if not file_path: 
            return

        try:
            filename = os.path.basename(file_path)
            target_path = os.path.join(MODEL_BASE_DIR, filename)
            
            if os.path.abspath(file_path) != os.path.abspath(target_path):
                shutil.copy2(file_path, target_path)
                msg = f"已將檔案複製到系統目錄:\n{filename}"
            else:
                msg = f"已選擇系統目錄內的檔案:\n{filename}"

            # ★ 修正 2：正確將匯入的檔名寫進 self.config["models"] 字典內
            if "models" not in self.config:
                self.config["models"] = {}
            self.config["models"][config_key] = filename
            
            line_edit.setText(filename)
            QMessageBox.information(self, "匯入成功", msg)
            
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"檔案複製失敗: {e}")

    def scan_images_by_date(self, root_dir, start_date, end_date):
        matched_files = []
        print(f"[Log] 開始掃描目錄: {root_dir}")
        
        if not os.path.exists(root_dir):
            print("[Error] 目錄不存在")
            return matched_files

        # ★ 修正 3：改用 os.walk 支援包含子資料夾的掃描
        try:
            for dirpath, _, filenames in os.walk(root_dir):
                for file_name in filenames:
                    if not file_name.lower().endswith(('.jpg', '.png', '.jpeg', '.bmp')):
                        continue

                    # 嘗試從檔名解析日期 (例如: 20260306_xxx.jpg)
                    try:
                        date_part = file_name[:8] 
                        file_date = datetime.strptime(date_part, "%Y%m%d").date()
                        
                        if start_date <= file_date <= end_date:
                            file_path = os.path.join(dirpath, file_name)
                            matched_files.append(file_path)
                    except ValueError:
                        continue
                        
        except Exception as e:
            print(f"[Error] 掃描過程出錯: {e}")
            traceback.print_exc()
        
        return matched_files

    def export_images(self, root_dir, cam_name):
        if not os.path.exists(root_dir):
            QMessageBox.warning(self, "路徑錯誤", f"找不到圖片路徑：\n{root_dir}\n請確認硬碟或資料夾是否正確。")
            return

        dlg = DateRangeDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return 

        start_date, end_date = dlg.get_dates()
        if start_date > end_date:
            QMessageBox.warning(self, "日期錯誤", "開始日期不能晚於結束日期！")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        files_to_zip = self.scan_images_by_date(root_dir, start_date, end_date)
        QApplication.restoreOverrideCursor()

        if not files_to_zip:
            QMessageBox.information(self, "查無資料", f"在 {start_date} 到 {end_date} 之間\n沒有找到 {cam_name} 的照片。")
            return

        zip_name = f"{cam_name.replace(' ','')}_{start_date}_{end_date}.zip"
        save_path, _ = QFileDialog.getSaveFileName(self, "儲存壓縮檔", zip_name, "Zip Files (*.zip)")
        
        if not save_path:
            return

        progress = QProgressDialog(f"正在打包 {len(files_to_zip)} 張圖片...", "取消", 0, len(files_to_zip), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, file_path in enumerate(files_to_zip):
                    if progress.wasCanceled():
                        break
                    
                    # 保持日期資料夾結構
                    rel_path = os.path.relpath(file_path, root_dir)
                    zf.write(file_path, rel_path)
                    
                    progress.setValue(i + 1)

            if not progress.wasCanceled():
                QMessageBox.information(self, "完成", f"✅ 匯出成功！\n共打包 {len(files_to_zip)} 張圖片。")
            else:
                if os.path.exists(save_path):
                    os.remove(save_path)

        except Exception as e:
            QMessageBox.critical(self, "匯出失敗", f"打包過程發生錯誤:\n{e}")
        finally:
            progress.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SettingsEditor()
    window.show()
    sys.exit(app.exec())