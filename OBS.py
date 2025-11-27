# plugins/OBS/OBS.py
"""
OBS Plugin (v5 via obsws-python)
Actions:
 - Toggle Stream
 - Toggle Record (Start/Stop)
 - Pause/Resume Recording
 - Save Replay Buffer
 - Switch Scene (with settings: pick scene)
 - Toggle Source Visibility (with settings: pick scene & source)
"""
import threading
import logging
import time
import os
import sys

import obsws_python as obs  # obsws-python (ReqClient wrapper for obs-websocket v5)
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from path_utils import resource_path

# ──────────────────────────────────────────────
# ✅ معلومات الإضافة
# ──────────────────────────────────────────────
ADDON_INFO = {
    "name": "OBS",
    "type": "OBS",
    "description": "Control streaming and recording in OBS Studio remotely",
    "version": "1.2.0",
    "author": "Bandar",
    "plugin_icon": "OBS.svg",  # Category icon
    "actions": [
        {
            "name": "Toggle Stream",
            "type": "OBS",
            "icon": "start_stream.svg",
            "description": "Start or stop streaming"
        },
        {
            "name": "Toggle Record",
            "type": "OBS",
            "icon": "start_rec.svg",
            "description": "Start or stop recording"
        },
        {
            "name": "Pause Rec",
            "type": "OBS",
            "icon": "pause_recording.svg",
            "description": "Pause or resume recording"
        },
        {
            "name": "Save Replay Buffer",
            "type": "OBS",
            "icon": "save_replay_buffer.svg",
            "description": "Save a video from Replay Buffer (if enabled in OBS)"
        },
        {
            "name": "Switch Scene",
            "type": "OBS",
            "icon": "switch_scene.svg",
            "description": "Switch to the specified scene",
            # هذا الأكشن يحتاج إعدادات (scene)
            "settings": [
                {
                    "type": "select",
                    "name": "scene",
                    "label": "Scene",
                    "options": [],  # تم تعبئتها ديناميًا في create_settings_widget
                    "required": True
                }
            ]
        },
        {
            "name": "Toggle Source",
            "type": "OBS",
            "icon": "show_element.svg",
            "description": "Toggle visibility of a source in a scene (on/off)",
            # يحتاج إعدادات: scene و source
            "settings": [
                {
                    "type": "select",
                    "name": "scene",
                    "label": "Scene",
                    "options": [],  # تعبئة ديناميكية
                    "required": True
                },
                {
                    "type": "select",
                    "name": "source",
                    "label": "Source",
                    "options": [],  # تعبئة ديناميكية بناءً على المشهد المختار
                    "required": True
                }
            ]
        }
    ]
}

# ──────────────────────────────────────────────
# تكوينات الاتصال
# ──────────────────────────────────────────────
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = ""  # ضبّطها أو ضع سلسلة فارغة إذا عطّلت المصادقة

# لوج بسيط
logging.basicConfig(level=logging.INFO, format='[OBSPlugin] %(message)s')
logger = logging.getLogger("OBSPlugin")


# ──────────────────────────────────────────────
# دوال مساعدة للتعامل مع ReqClient
# ──────────────────────────────────────────────
def obs_action(method, *args, **kwargs):
    """
    Helper: يفتح ReqClient، ينفّذ method ثم يغلق الاتصال.
    method يستلم الـ client كأول باراميتر.
    """
    import sys
    import io
    
    # Temporarily suppress stderr to hide obsws-python connection errors
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    
    try:
        with obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD, timeout=5) as client:
            sys.stderr = old_stderr  # Restore stderr on success
            return method(client, *args, **kwargs)
    except ConnectionRefusedError:
        sys.stderr = old_stderr  # Restore stderr
        # OBS not running or WebSocket not enabled - don't spam logs
        logger.info("Cannot connect to OBS (not running or WebSocket disabled)")
        return None
    except Exception as e:
        sys.stderr = old_stderr  # Restore stderr
        # Only log if it's not a connection error
        if "connection" not in str(e).lower():
            logger.error(f"OBS request error: {e}")
        return None
    finally:
        # Ensure stderr is always restored
        sys.stderr = old_stderr


def safe_getattr(obj, *names, default=False):
    """
    محاولة الحصول على أي اسم من الأسماء المحتملة (مرونة مع اختلاف أسماء الحقول).
    """
    if obj is None:
        return default
    for n in names:
        try:
            val = getattr(obj, n)
            if val is not None:
                return val
        except Exception:
            pass
        # بعض الاستجابات قد تكون dict-like
        try:
            if isinstance(obj, dict) and n in obj:
                return obj[n]
        except Exception:
            pass
    return default


# ──────────────────────────────────────────────
# ✅ فئة الإضافة
# ──────────────────────────────────────────────
class OBSPlugin:
    """OBS Plugin: مجموعة أوامر للتحكم بالـ OBS عبر obsws-python (v5)."""

    def execute_action(self, action_name, action_data):
        try:
            # توجيه الأكشنات
            name = action_name.strip().lower()
            if name == "toggle stream":
                threading.Thread(target=self.toggle_stream, daemon=True).start()
                return True
            elif name == "toggle record":
                threading.Thread(target=self.toggle_record, daemon=True).start()
                return True
            elif name == "pause rec":
                threading.Thread(target=self.toggle_pause_record, daemon=True).start()
                return True
            elif name == "save replay buffer":
                threading.Thread(target=self.save_replay_buffer, daemon=True).start()
                return True
            elif name == "switch scene":
                threading.Thread(target=self.switch_scene, args=(action_data,), daemon=True).start()
                return True
            elif name == "toggle source":
                threading.Thread(target=self.toggle_source_visibility, args=(action_data,), daemon=True).start()
                return True
            else:
                logger.error(f"❌ Unknown action: {action_name}")
                return False
        except Exception as e:
            logger.exception(f"⚠️ Error executing action {action_name}: {e}")
            return False

    # ---------- Stream ----------
    def toggle_stream(self):
        def _fn(client: obs.ReqClient):
            try:
                resp = client.get_stream_status()
                is_streaming = safe_getattr(resp, "output_active", "streaming", "streaming_active", default=False)
                logger.info(f"Streaming status: {is_streaming}")
                if is_streaming:
                    client.stop_stream()
                    logger.info("❌ أوقف البث")
                else:
                    client.start_stream()
                    logger.info("✅ بدأ البث")
            except Exception as e:
                logger.exception(f"Error toggling stream: {e}")

        obs_action(_fn)

    # ---------- Record (start/stop) ----------
    def toggle_record(self):
        def _fn(client: obs.ReqClient):
            try:
                resp = client.get_record_status()
                is_recording = safe_getattr(resp, "output_active", "recording", "is_recording", default=False)
                logger.info(f"Recording status: {is_recording}")
                if is_recording:
                    client.stop_record()
                    logger.info("❌ أوقف التسجيل")
                else:
                    client.start_record()
                    logger.info("✅ بدأ التسجيل")
            except Exception as e:
                logger.exception(f"Error toggling record: {e}")

        obs_action(_fn)

    # ---------- Pause / Resume Recording ----------
    def toggle_pause_record(self):
        """
        يحاول استدعاء ToggleRecordPause إذا متاح
        أو يستخدم PauseRecord/ResumeRecord إذا لازم.
        """
        def _fn(client: obs.ReqClient):
            try:
                resp = client.get_record_status()
                is_paused = safe_getattr(resp, "is_paused", "paused", default=False)
                is_recording = safe_getattr(resp, "output_active", "recording", default=False)
                logger.info(f"Recording active: {is_recording} | paused: {is_paused}")

                if not is_recording:
                    logger.info("Recording is not active — cannot pause/resume.")
                    return

                # أولاً جرّب toggle_record_pause
                if hasattr(client, "toggle_record_pause"):
                    client.toggle_record_pause()
                    logger.info("🔄 استخدم ToggleRecordPause للتبديل بين إيقاف/استئناف التسجيل")
                    return

                # fallback: Pause/Resume
                if hasattr(client, "pause_record") and hasattr(client, "resume_record"):
                    if is_paused:
                        client.resume_record()
                        logger.info("✅ استأنف التسجيل (ResumeRecord)")
                    else:
                        client.pause_record()
                        logger.info("⏸️ أوقف التسجيل مؤقتًا (PauseRecord)")
                else:
                    logger.warning("Pause/Resume recording not supported by this client/library version.")
            except Exception as e:
                logger.exception(f"Error toggling pause/resume record: {e}")

        obs_action(_fn)

    # ---------- Save Replay Buffer ----------
    def save_replay_buffer(self):
        def _fn(client: obs.ReqClient):
            try:
                # SaveReplayBuffer عادة لا يحتاج براميتر
                if hasattr(client, "save_replay_buffer"):
                    client.save_replay_buffer()
                    logger.info("✅ طلب حفظ Replay Buffer أرسِل إلى OBS")
                else:
                    logger.warning("Save Replay Buffer is not supported by this client/library version.")
            except Exception as e:
                logger.exception(f"Error saving replay buffer: {e}")

        obs_action(_fn)

    # ---------- Switch Scene ----------
    def switch_scene(self, settings=None):
        """
        settings: dict with key 'scene' (scene name)
        """
        scene_name = (settings or {}).get("scene") if isinstance(settings, dict) else None
        if not scene_name:
            logger.error("No scene provided to switch_scene.")
            return

        def _fn(client: obs.ReqClient, target_scene):
            try:
                # Attempt to use set_current_program_scene or set_current_scene depending on client
                if hasattr(client, "set_current_program_scene"):
                    client.set_current_program_scene(target_scene)
                    logger.info(f"✅ تم تغيير المشهد إلى: {target_scene}")
                elif hasattr(client, "set_current_scene"):
                    # older naming
                    client.set_current_scene(scene_name=target_scene)
                    logger.info(f"✅ تم تغيير المشهد إلى: {target_scene}")
                else:
                    logger.warning("Switch scene method not available in this client/library version.")
            except Exception as e:
                logger.exception(f"Error switching scene to {target_scene}: {e}")

        obs_action(lambda c: _fn(c, scene_name))

    # ---------- Toggle Source Visibility ----------
    def toggle_source_visibility(self, settings=None):
        """
        settings: dict with keys 'scene' and 'source'
        """
        scene = (settings or {}).get("scene")
        source = (settings or {}).get("source")
        if not scene or not source:
            logger.error("scene and source must be provided for Toggle Source Visibility.")
            return

        def _fn(client: obs.ReqClient, scene_name, source_name):
            try:
                # جلب عناصر المشهد مع التعامل مع اختلاف أسماء البراميترات بين الإصدارات
                resp = None
                try:
                    resp = client.get_scene_item_list(scene_name=scene_name)
                except TypeError:
                    try:
                        resp = client.get_scene_item_list(sceneName=scene_name)
                    except TypeError:
                        try:
                            resp = client.get_scene_item_list(scene_name)
                        except Exception:
                            resp = None

                if resp is None:
                    logger.error(f"❌ تعذّر جلب عناصر المشهد '{scene_name}'")
                    return

                # استخراج العناصر من الاستجابة بشكل متسامح مع الأشكال المختلفة
                items = []
                try:
                    if hasattr(resp, "sceneItems"):
                        items = getattr(resp, "sceneItems") or []
                    elif hasattr(resp, "scene_items"):
                        items = getattr(resp, "scene_items") or []
                    elif hasattr(resp, "items"):
                        items = getattr(resp, "items") or []
                    elif isinstance(resp, dict):
                        items = resp.get("sceneItems") or resp.get("scene_items") or resp.get("items") or []
                    elif hasattr(resp, "datain") and isinstance(resp.datain, dict):
                        items = resp.datain.get("sceneItems") or resp.datain.get("scene_items") or []
                except Exception:
                    items = []

                # العثور على العنصر المطلوب بحسب اسم المصدر
                found_item = None
                for it in items:
                    nm = it.get("sourceName") if isinstance(it, dict) else (
                        getattr(it, "sourceName", None)
                        or getattr(it, "source_name", None)
                        or getattr(it, "inputName", None)
                        or getattr(it, "name", None)
                    )
                    if nm == source_name:
                        found_item = it
                        break

                if not found_item:
                    logger.error(f"❌ المصدر '{source_name}' غير موجود في المشهد '{scene_name}'")
                    return

                # قراءة sceneItemId والحالة الحالية
                item_id = (
                    found_item.get("sceneItemId") if isinstance(found_item, dict)
                    else getattr(found_item, "sceneItemId", None)
                    or getattr(found_item, "scene_item_id", None)
                    or getattr(found_item, "id", None)
                )
                enabled = (
                    found_item.get("sceneItemEnabled") if isinstance(found_item, dict)
                    else getattr(found_item, "sceneItemEnabled", None)
                    or getattr(found_item, "scene_item_enabled", None)
                    or getattr(found_item, "enabled", None)
                )

                if item_id is None:
                    logger.error(f"❌ لم يتم العثور على sceneItemId للمصدر '{source_name}'")
                    return

                # تبديل الحالة
                new_state = not bool(enabled)
                try:
                    client.set_scene_item_enabled(scene_name=scene_name, scene_item_id=item_id, scene_item_enabled=new_state)
                except TypeError:
                    try:
                        client.set_scene_item_enabled(sceneName=scene_name, sceneItemId=item_id, sceneItemEnabled=new_state)
                    except TypeError:
                        # استدعاء موضعي بدون أسماء
                        client.set_scene_item_enabled(scene_name, item_id, new_state)

                logger.info(f"✅ تبديل رؤية '{source_name}' في المشهد '{scene_name}' إلى {new_state}")

            except Exception as e:
                logger.exception(f"Error toggling source visibility for {source_name} in {scene_name}: {e}")

        obs_action(lambda c: _fn(c, scene, source))

    # ---------- Settings data preparation (for async loading) ----------
    def prepare_settings_data(self, action_name, saved_values):
        """تحضير بيانات الإعدادات في خيط منفصل (بدون Qt widgets)"""
        try:
            name = (action_name or "").strip().lower()
            if name not in ("switch scene", "toggle source"):
                return None
            
            print(f"[OBSPlugin] Preparing settings data for: {action_name}")
            
            # Helper to fetch scenes
            def _fetch_scenes(client):
                try:
                    if hasattr(client, "get_scene_list"):
                        resp = client.get_scene_list()
                        if resp is None:
                            return []
                        if hasattr(resp, "scenes"):
                            raw = getattr(resp, "scenes")
                        elif isinstance(resp, dict):
                            raw = resp.get("scenes", [])
                        else:
                            raw = []
                        out = []
                        for s in raw:
                            name = s.get("sceneName") if isinstance(s, dict) else getattr(s, "scene_name", None) or getattr(s, "sceneName", None)
                            if name:
                                out.append(str(name))
                        return out
                    else:
                        return []
                except Exception:
                    return []
            
            # جلب قائمة المشاهد في الخيط المنفصل
            scenes_list = obs_action(lambda c: _fetch_scenes(c)) or []

            # تحقق هل OBS يعمل (يتم في الخلفية لتجنب أي تأخير في واجهة Qt)
            obs_running = False
            try:
                import psutil
            except Exception:
                psutil = None
            if psutil is not None:
                try:
                    for proc in psutil.process_iter(['name']):
                        if 'obs' in (proc.info.get('name') or '').lower():
                            obs_running = True
                            break
                except Exception:
                    pass
            else:
                try:
                    import subprocess, sys
                    if sys.platform.startswith('win'):
                        out = subprocess.check_output(["tasklist"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        s = out.decode("utf-8", errors="ignore").lower()
                        obs_running = ("obs64.exe" in s) or ("obs.exe" in s)
                except Exception:
                    pass

            return {
                'scenes_list': scenes_list,
                'saved_values': saved_values,
                'action_name': action_name,
                'obs_running': obs_running,
            }
            
        except Exception as e:
            print(f"[OBSPlugin] Error preparing settings data: {e}")
            return None

    # ---------- Settings widget creator ----------
    def create_settings_widget(self, action_name, saved_values, parent=None):
        """
        Create PyQt6 widget for actions that need settings (Switch Scene, Toggle Source).
        For Switch Scene: dropdown of scenes.
        For Toggle Source: dropdown of scenes, and dropdown of sources in the selected scene.
        If fetching scenes fails, show error message.
        """
        try:
            name = (action_name or "").strip().lower()
            if name not in ("switch scene", "toggle source"):
                return None

            # lazy import PyQt widgets (same pattern as commands.py)
            from PyQt6 import QtWidgets, QtCore
            from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QSizePolicy
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize

            class ArrowAwareComboBox(QComboBox):
                def __init__(self, parent=None):
                    super().__init__(parent)
                    self.setMinimumHeight(40)
                    down = resource_path("icons/Arrow-down.svg").replace("\\", "/")
                    up = resource_path("icons/Arrow-up.svg").replace("\\", "/")
                    tpl = (
                        "QComboBox {\n"
                        "    background-color: #0f1115;\n"
                        "    color: #ffffff;\n"
                        "    border: 1px solid #2a2f36;\n"
                        "    border-radius: 8px;\n"
                        "    padding: 5px 10px;\n"
                        "    font-size: 13px;\n"
                        "}\n"
                        "QComboBox:hover { border: 1px solid #4a90e2; }\n"
                        "QComboBox::drop-down {\n"
                        "    subcontrol-origin: padding;\n"
                        "    subcontrol-position: top right;\n"
                        "    width: 25px;\n"
                        "    border-left-width: 1px;\n"
                        "    border-left-color: #2a2f36;\n"
                        "    border-left-style: solid;\n"
                        "    border-top-right-radius: 8px;\n"
                        "    border-bottom-right-radius: 8px;\n"
                        "}\n"
                        "QComboBox::down-arrow { image: url(ARROW); width: 16px; height: 16px; }\n"
                        "QComboBox QAbstractItemView { background-color: #1e2228; color: #ffffff; selection-background-color: #2a2f36; border: 1px solid #2a2f36; outline: none; padding: 6px; border-radius: 8px; margin-top: 3px; }\n"
                    )
                    self._style_down = tpl.replace("ARROW", down)
                    self._style_up = tpl.replace("ARROW", up)
                    self.setStyleSheet(self._style_down)
                def showPopup(self):
                    self.setStyleSheet(self._style_up)
                    super().showPopup()
                def hidePopup(self):
                    super().hidePopup()
                    self.setStyleSheet(self._style_down)

            # Helper to fetch scenes
            scenes_list = []

            def _fetch_scenes(client):
                try:
                    if hasattr(client, "get_scene_list"):
                        resp = client.get_scene_list()
                        # resp might have .scenes or dict-like
                        if resp is None:
                            return []
                        if hasattr(resp, "scenes"):
                            raw = getattr(resp, "scenes")
                        elif isinstance(resp, dict):
                            raw = resp.get("scenes", [])
                        else:
                            raw = []
                        out = []
                        for s in raw:
                            # s may be dict with "sceneName" or "scene_name" etc.
                            name = s.get("sceneName") if isinstance(s, dict) else getattr(s, "scene_name", None) or getattr(s, "sceneName", None)
                            if name:
                                out.append(str(name))
                        return out
                    else:
                        return []
                except Exception:
                    return []

            # استخدام البيانات المحضرة إذا توفرت
            if isinstance(saved_values, dict) and 'scenes_list' in saved_values:
                scenes_list = saved_values['scenes_list']
                print(f"[OBSPlugin] Using pre-loaded scenes data: {len(scenes_list)} scenes")
            else:
                scenes_list = obs_action(lambda c: _fetch_scenes(c)) or []
                print(f"[OBSPlugin] Loading scenes on-demand: {len(scenes_list)} scenes")

            widget = QWidget(parent)
            widget.setStyleSheet("background-color: #0f1115; border: none;")
            main_layout = QVBoxLayout(widget)
            main_layout.setContentsMargins(10, 10, 10, 10)
            main_layout.setSpacing(15)
            main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

            # Scene selector (for both actions)
            scene_container = QWidget()
            scene_container.setStyleSheet("background-color: #171a1f; border-radius: 8px;")
            scene_container.setMaximumWidth(300)
            scene_layout = QVBoxLayout(scene_container)
            scene_layout.setContentsMargins(15, 15, 15, 15)
            scene_layout.setSpacing(12)

            scene_header_group = QHBoxLayout()
            scene_header_group.setSpacing(10)
            scene_header_icon = QLabel()
            scene_header_icon.setPixmap(QIcon(resource_path("icons/switch_scene.svg")).pixmap(QSize(22, 22)))
            scene_header_icon.setFixedSize(22, 22)
            scene_header_group.addWidget(scene_header_icon)
            scene_header_label = QLabel("Scene")
            scene_header_label.setStyleSheet("color: #5cc8ff; font-size: 16px; font-weight: bold;")
            scene_header_group.addWidget(scene_header_label)
            scene_centered_header = QHBoxLayout()
            scene_centered_header.addStretch()
            scene_centered_header.addLayout(scene_header_group)
            scene_centered_header.addStretch()
            scene_layout.addLayout(scene_centered_header)

            scene_combo = ArrowAwareComboBox()
            scene_combo.setObjectName("scene")
            scene_combo.setProperty("setting_key", "scene")
            # populate scenes
            if scenes_list:
                for s in scenes_list:
                    scene_combo.addItem(s, userData=s)
                
                # restore saved value if any
                saved_scene = (saved_values or {}).get("scene")
                if saved_scene:
                    for i in range(scene_combo.count()):
                        if str(scene_combo.itemData(i)) == str(saved_scene):
                            scene_combo.setCurrentIndex(i)
                            break
                
                scene_layout.addWidget(scene_combo)
                main_layout.addWidget(scene_container)
            else:
                # Show error message instead of manual input
                scene_combo.setEnabled(False)
                scene_combo.addItem("⚠️ Cannot connect to OBS", userData=None)
                scene_layout.addWidget(scene_combo)
                
                # Add informative message
                error_label = QLabel()
                error_label.setWordWrap(True)
                error_label.setStyleSheet(
                    """
                    QLabel {
                        font-size: 12px;
                        color: #ff6b6b;
                        padding: 8px;
                        background: transparent;
                    }
                    """
                )
                
                # استخدم القيمة القادمة من التحضير في الخلفية لتجنب فحص العمليات على الخيط الرئيسي
                obs_running = bool((saved_values or {}).get('obs_running'))
                if obs_running:
                    error_label.setText("⚠️ OBS is running but WebSocket is not enabled.\n\nPlease enable WebSocket in OBS:\nTools → WebSocket Server Settings\n\nNote: Disable authentication (uncheck 'Enable Authentication')")
                else:
                    error_label.setText("⚠️ Cannot reach OBS.\n\nStart OBS Studio or enable WebSocket in OBS:\nTools → WebSocket Server Settings")
                
                scene_layout.addWidget(error_label)
                main_layout.addWidget(scene_container)
                return widget  # Return early, no point showing source selector

            # If action is Toggle Source, we need source selector too
            source_combo = None
            if name == "toggle source":
                source_container = QWidget()
                source_container.setStyleSheet("background-color: #171a1f; border-radius: 8px;")
                source_container.setMaximumWidth(300)
                source_layout = QVBoxLayout(source_container)
                source_layout.setContentsMargins(15, 15, 15, 15)
                source_layout.setSpacing(12)

                source_header_group = QHBoxLayout()
                source_header_group.setSpacing(10)
                source_header_icon = QLabel()
                source_header_icon.setPixmap(QIcon(resource_path("icons/show_element.svg")).pixmap(QSize(22, 22)))
                source_header_icon.setFixedSize(22, 22)
                source_header_group.addWidget(source_header_icon)
                source_header_label = QLabel("Source")
                source_header_label.setStyleSheet("color: #5cc8ff; font-size: 16px; font-weight: bold;")
                source_header_group.addWidget(source_header_label)
                source_centered_header = QHBoxLayout()
                source_centered_header.addStretch()
                source_centered_header.addLayout(source_header_group)
                source_centered_header.addStretch()
                source_layout.addLayout(source_centered_header)

                source_combo = ArrowAwareComboBox()
                source_combo.setObjectName("source")
                source_combo.setProperty("setting_key", "source")

                # function to fetch sources for a scene
                def _fetch_sources_for_scene(scene_name):
                    try:
                        def inner(client):
                            # Try multiple variants to get scene items (different library versions/param names)
                            resp = None
                            if hasattr(client, "get_scene_item_list"):
                                try:
                                    resp = client.get_scene_item_list(scene_name=scene_name)
                                except TypeError:
                                    try:
                                        resp = client.get_scene_item_list(sceneName=scene_name)
                                    except TypeError:
                                        try:
                                            resp = client.get_scene_item_list(scene_name)
                                        except Exception:
                                            resp = None
                            elif hasattr(client, "get_scene_items"):
                                try:
                                    resp = client.get_scene_items(scene_name=scene_name)
                                except TypeError:
                                    try:
                                        resp = client.get_scene_items(sceneName=scene_name)
                                    except TypeError:
                                        try:
                                            resp = client.get_scene_items(scene_name)
                                        except Exception:
                                            resp = None
                            else:
                                logger.warning("Scene item listing not supported by this client/library version.")
                                resp = None

                            # Extract list of items from response in a tolerant way
                            raw_items = []
                            if resp is not None:
                                try:
                                    for attr in ("scene_items", "sceneItems", "items"):
                                        if hasattr(resp, attr):
                                            raw_items = getattr(resp, attr) or []
                                            break
                                    if not raw_items and isinstance(resp, dict):
                                        for key in ("sceneItems", "scene_items", "items"):
                                            if key in resp:
                                                raw_items = resp.get(key) or []
                                                break
                                    # some wrappers keep raw data in datain
                                    if not raw_items and hasattr(resp, "datain") and isinstance(resp.datain, dict):
                                        raw_items = resp.datain.get("sceneItems") or resp.datain.get("scene_items") or []
                                except Exception:
                                    raw_items = []

                            # Build source names from items
                            out = []
                            try:
                                for it in raw_items:
                                    if isinstance(it, dict):
                                        nm = it.get("sourceName") or it.get("source_name") or it.get("inputName") or it.get("name")
                                    else:
                                        nm = getattr(it, "source_name", None) or getattr(it, "sourceName", None) or getattr(it, "inputName", None) or getattr(it, "name", None)
                                    if nm:
                                        out.append(str(nm))
                            except Exception:
                                out = []

                            # Fallback: if we couldn't fetch scene items, list all inputs so user at least gets options
                            if not out:
                                try:
                                    inputs_resp = None
                                    if hasattr(client, "get_input_list"):
                                        inputs_resp = client.get_input_list()
                                    elif hasattr(client, "get_sources_list"):
                                        inputs_resp = client.get_sources_list()

                                    inputs = []
                                    if inputs_resp is not None:
                                        if isinstance(inputs_resp, dict):
                                            inputs = inputs_resp.get("inputs") or inputs_resp.get("sources") or []
                                        else:
                                            for attr in ("inputs", "sources"):
                                                if hasattr(inputs_resp, attr):
                                                    inputs = getattr(inputs_resp, attr) or []
                                                    break
                                    for inp in inputs:
                                        if isinstance(inp, dict):
                                            nm = inp.get("inputName") or inp.get("name") or inp.get("sourceName")
                                        else:
                                            nm = getattr(inp, "inputName", None) or getattr(inp, "name", None) or getattr(inp, "sourceName", None)
                                        if nm:
                                            out.append(str(nm))
                                except Exception:
                                    pass

                            return out

                        return obs_action(inner) or []
                    except Exception:
                        return []

                # populate sources initially using selected scene (if any)
                initial_scene = None
                if scenes_list and scene_combo.count() > 0:
                    initial_scene = scene_combo.currentData()
                
                if initial_scene:
                    sources = _fetch_sources_for_scene(initial_scene)
                else:
                    sources = []

                if sources:
                    for s in sources:
                        source_combo.addItem(s, userData=s)
                    
                    # restore saved source
                    saved_src = (saved_values or {}).get("source")
                    if saved_src:
                        for i in range(source_combo.count()):
                            if str(source_combo.itemData(i)) == str(saved_src):
                                source_combo.setCurrentIndex(i)
                                break
                else:
                    source_combo.setEnabled(False)
                    source_combo.addItem("No sources in this scene", userData=None)

                source_layout.addWidget(source_combo)
                main_layout.addWidget(source_container)

                # when scene changes, try to refresh sources
                def on_scene_changed(idx):
                    try:
                        scene_val = scene_combo.itemData(idx)
                        if not scene_val:
                            return
                        
                        # fetch sources for new scene
                        new_sources = _fetch_sources_for_scene(scene_val)
                        source_combo.blockSignals(True)
                        source_combo.clear()
                        
                        if new_sources:
                            source_combo.setEnabled(True)
                            for s in new_sources:
                                source_combo.addItem(s, userData=s)
                        else:
                            source_combo.setEnabled(False)
                            source_combo.addItem("No sources in this scene", userData=None)
                        
                        source_combo.blockSignals(False)
                    except Exception:
                        pass

                scene_combo.currentIndexChanged.connect(on_scene_changed)

            return widget

        except Exception as e:
            logger.exception(f"Error creating settings widget: {e}")
            return None


# ──────────────────────────────────────────────
# ✅ تصدير نسخة الإضافة
# ──────────────────────────────────────────────
plugin_instance = OBSPlugin()
