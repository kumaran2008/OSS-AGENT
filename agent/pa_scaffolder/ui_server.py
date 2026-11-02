import json
import threading
import urllib.parse
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional

from agent.core.dynamic_auth import auth_manager
from llm.fast_streamer import fast_streamer
from agent.pa_scaffolder.vision_engine import MultimodalVisionEngine
from agent.pa_scaffolder.face_recognizer import FaceRecognizer
from agent.pa_scaffolder.social_engine import SocialMediaEngine


class CompanionUIState:
    message: str = "Ready and standing by."
    ghost: bool = False
    state: str = "IDLE"


UI_STATE = CompanionUIState()
_GLOBAL_CHATBOT = None


def get_chatbot():
    global _GLOBAL_CHATBOT
    if _GLOBAL_CHATBOT is None:
        from agent.chat_interface import AutonomousChatBot
        _GLOBAL_CHATBOT = AutonomousChatBot()
    return _GLOBAL_CHATBOT


COOL_GLASS_UI = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OSS-Agent :: AI Engineering & Companion Workstation</title>
  <style>
    :root {
      --bg: #07090E;
      --card: rgba(18, 24, 38, 0.7);
      --border: rgba(0, 255, 204, 0.2);
      --accent: #00FFCC;
      --accent-glow: rgba(0, 255, 204, 0.4);
      --text: #F1F5F9;
      --subtext: #94A3B8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: radial-gradient(circle at 50% 0%, #111A2C 0%, var(--bg) 75%);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      height: 100vh;
      display: flex;
      overflow: hidden;
    }
    #sidebar {
      width: 280px;
      border-right: 1px solid var(--border);
      background: var(--card);
      backdrop-filter: blur(16px);
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    #chat-container {
      flex: 1;
      display: flex;
      flex-direction: column;
      position: relative;
    }
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 30px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .msg {
      max-width: 80%;
      padding: 14px 18px;
      border-radius: 12px;
      line-height: 1.5;
      font-size: 14px;
      animation: fadeIn 0.15s ease-out;
    }
    .msg.user {
      align-self: flex-end;
      background: #1E293B;
      border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .msg.assistant {
      align-self: flex-start;
      background: rgba(14, 23, 42, 0.8);
      border: 1px solid var(--border);
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    #input-box {
      padding: 20px 30px;
      background: var(--card);
      border-top: 1px solid var(--border);
      display: flex;
      gap: 12px;
      align-items: center;
    }
    input[type="text"] {
      flex: 1;
      background: #0F172A;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      color: var(--text);
      font-size: 14px;
      outline: none;
    }
    input[type="text"]:focus { border-color: var(--accent); box-shadow: 0 0 10px var(--accent-glow); }
    button {
      background: var(--accent);
      color: #05101A;
      font-weight: 700;
      border: none;
      padding: 12px 20px;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s;
    }
    button:hover { box-shadow: 0 0 15px var(--accent-glow); }
    #companion-orb {
      position: absolute;
      top: 30px;
      right: 30px;
      width: 110px;
      height: 110px;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 35%, #1E293B, #070B12 80%);
      border: 2px solid var(--accent);
      box-shadow: 0 0 30px var(--accent-glow), inset 0 0 15px var(--accent-glow);
      display: flex;
      justify-content: center;
      align-items: center;
      cursor: grab;
      transition: transform 0.2s ease, border-color 0.2s;
      z-index: 100;
    }
    #companion-orb.drag-hover {
      transform: scale(1.15);
      border-color: #FF007F;
      box-shadow: 0 0 40px rgba(255, 0, 127, 0.6);
    }
    .eye {
      width: 22px;
      height: 32px;
      background: var(--accent);
      border-radius: 50%;
      margin: 0 8px;
      position: relative;
      box-shadow: 0 0 12px var(--accent);
      transition: all 0.15s ease-out;
    }
    .pupil {
      width: 10px;
      height: 12px;
      background: #070B12;
      border-radius: 50%;
      position: absolute;
      top: 10px;
      left: 6px;
      transition: transform 0.05s ease-out;
    }
    #modal {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.7);
      backdrop-filter: blur(8px);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 1000;
    }
    #modal-content {
      background: #0F172A;
      border: 1px solid var(--border);
      padding: 30px;
      border-radius: 16px;
      width: 440px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.6);
    }
  </style>
</head>
<body>
  <div id="sidebar">
    <h2 style="color: var(--accent); font-size: 16px; letter-spacing: 1px;">AEGIS :: OSS-AGENT</h2>
    <div style="font-size: 12px; color: var(--subtext);">Autonomous Engineering & Companion Engine</div>
    <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.08);">
    
    <div style="font-size: 12px; font-weight: bold; color: var(--accent);">SYSTEM STATUS</div>
    <div id="auth-status" style="font-size: 12px; color: var(--subtext);">Checking credentials...</div>
    <button onclick="openModal()" style="font-size: 12px; padding: 8px 12px;">Manage API Keys</button>

    <div style="margin-top: auto; font-size: 11px; color: var(--subtext);">
      • Drop photo on Orb: Analyzes food, recognizes faces, or drafts social posts.<br>
      • OS Automation: Open apps, scroll, and tap.<br>
      • Latency: Sub-100ms Streaming.
    </div>
  </div>

  <div id="chat-container">
    <div id="companion-orb" title="Drag photos here to analyze!">
      <div class="eye" id="eye-left"><div class="pupil" id="pupil-left"></div></div>
      <div class="eye" id="eye-right"><div class="pupil" id="pupil-right"></div></div>
    </div>

    <div id="messages">
      <div class="msg assistant">
        <strong>Aegis OSS-Agent Online</strong><br>
        Memory active. Ask questions, issue engineering tasks, or drop photos directly onto my 3D face.
      </div>
    </div>

    <div id="input-box">
      <input type="text" id="user-input" placeholder="Type a message or instruction..." autofocus>
      <button onclick="sendMessage()">Send</button>
    </div>
  </div>

  <div id="modal">
    <div id="modal-content">
      <h3 style="color: var(--accent);">Authentication Credentials</h3>
      <label style="font-size: 12px;">OpenRouter API Key:</label>
      <input type="text" id="key-openrouter" placeholder="sk-or-v1-...">
      
      <label style="font-size: 12px;">GitHub Classic Token (repo scope):</label>
      <input type="text" id="key-github" placeholder="ghp_...">

      <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 10px;">
        <button onclick="closeModal()" style="background: transparent; color: var(--subtext); border: 1px solid var(--border);">Cancel</button>
        <button onclick="saveKeys()">Save & Hot-Reload</button>
      </div>
    </div>
  </div>

  <script>
    const orb = document.getElementById('companion-orb');
    const pLeft = document.getElementById('pupil-left');
    const pRight = document.getElementById('pupil-right');
    const eyeL = document.getElementById('eye-left');
    const eyeR = document.getElementById('eye-right');
    const messages = document.getElementById('messages');
    const input = document.getElementById('user-input');

    window.addEventListener('mousemove', (e) => {
      const rect = orb.getBoundingClientRect();
      const ox = rect.left + rect.width / 2;
      const oy = rect.top + rect.height / 2;
      const dx = Math.max(-6, Math.min(6, (e.clientX - ox) / 25));
      const dy = Math.max(-7, Math.min(7, (e.clientY - oy) / 25));
      pLeft.style.transform = `translate(${dx}px, ${dy}px)`;
      pRight.style.transform = `translate(${dx}px, ${dy}px)`;
    });

    setInterval(() => {
      eyeL.style.height = '2px'; eyeR.style.height = '2px';
      setTimeout(() => { eyeL.style.height = '32px'; eyeR.style.height = '32px'; }, 130);
    }, 4000);

    orb.addEventListener('dragover', (e) => { e.preventDefault(); orb.classList.add('drag-hover'); });
    orb.addEventListener('dragleave', () => orb.classList.remove('drag-hover'));
    orb.addEventListener('drop', async (e) => {
      e.preventDefault();
      orb.classList.remove('drag-hover');
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        appendMsg('user', `Uploaded photo: ${files[0].name}`);
        const formData = new FormData();
        formData.append('photo', files[0]);
        appendMsg('assistant', `Analyzing ${files[0].name}...`);
        try {
          const res = await fetch('/api/vision_upload', { method: 'POST', body: formData });
          const json = await res.json();
          appendMsg('assistant', json.result || 'Image parsed successfully.');
        } catch(err) {
          appendMsg('assistant', 'Error parsing image: ' + err);
        }
      }
    });

    async function sendMessage() {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      appendMsg('user', text);

      const botMsgDiv = appendMsg('assistant', '');
      try {
        const response = await fetch('/api/chat_stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          botMsgDiv.innerHTML += decoder.decode(value);
          messages.scrollTop = messages.scrollHeight;
        }
      } catch (err) {
        botMsgDiv.textContent = 'Streaming error: ' + err;
      }
    }

    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });

    function appendMsg(role, text) {
      const d = document.createElement('div');
      d.className = 'msg ' + role;
      d.innerHTML = text;
      messages.appendChild(d);
      messages.scrollTop = messages.scrollHeight;
      return d;
    }

    function openModal() { document.getElementById('modal').style.display = 'flex'; }
    function closeModal() { document.getElementById('modal').style.display = 'none'; }
    async function saveKeys() {
      const orKey = document.getElementById('key-openrouter').value.trim();
      const ghKey = document.getElementById('key-github').value.trim();
      if (orKey) await fetch('/api/save_key', { method: 'POST', body: JSON.stringify({ key: 'OPENROUTER_API_KEY', value: orKey }) });
      if (ghKey) await fetch('/api/save_key', { method: 'POST', body: JSON.stringify({ key: 'GITHUB_TOKEN', value: ghKey }) });
      closeModal();
      checkAuth();
    }
    async function checkAuth() {
      const res = await fetch('/api/auth_status');
      const data = await res.json();
      document.getElementById('auth-status').innerHTML = `
        OpenRouter: ${data.OPENROUTER_API_KEY ? '✅ Active' : '❌ Missing'}<br>
        GitHub: ${data.GITHUB_TOKEN ? '✅ Active' : '❌ Missing'}
      `;
    }
    checkAuth();
  </script>
</body>
</html>
"""


class FastUIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(COOL_GLASS_UI.encode("utf-8"))
        elif self.path == "/api/auth_status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            creds = auth_manager.detect_missing_credentials()
            self.wfile.write(json.dumps(creds).encode("utf-8"))
        elif self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            payload = {
                "message": UI_STATE.message,
                "ghost": UI_STATE.ghost,
                "state": UI_STATE.state
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            if self.path == "/api/chat_stream":
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len).decode("utf-8")) if content_len > 0 else {}
                user_msg = body.get("message", "")

                bot = get_chatbot()
                device_intent = bot.handle_device_action(user_msg)
                builder_intent = bot.handle_pa_builder_intent(user_msg)

                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                if device_intent:
                    bot.conv_mem.log_message("user", user_msg)
                    bot.conv_mem.log_message("assistant", device_intent)
                    self._send_chunk(device_intent.encode("utf-8"))
                elif builder_intent:
                    bot.conv_mem.log_message("user", user_msg)
                    bot.conv_mem.log_message("assistant", builder_intent)
                    self._send_chunk(builder_intent.encode("utf-8"))
                else:
                    bot.conv_mem.log_message("user", user_msg)
                    recent_turns = bot.conv_mem.get_recent_history(limit=6)
                    messages = [{"role": "system", "content": bot._build_system_prompt(user_msg)}]
                    messages.extend(recent_turns)

                    full_reply = []
                    for token in fast_streamer.stream_complete(messages):
                        full_reply.append(token)
                        self._send_chunk(token.encode("utf-8"))

                    bot.conv_mem.log_message("assistant", "".join(full_reply))

                self._send_chunk(b"")

            elif self.path == "/api/save_key":
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                k, v = body.get("key"), body.get("value")
                ok, msg = auth_manager.update_key(k, v)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": ok, "message": msg}).encode("utf-8"))

            elif self.path == "/api/vision_upload":
                content_len = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_len)

                temp_img = Path("./workspace/dropped_image.jpg")
                temp_img.parent.mkdir(parents=True, exist_ok=True)
                temp_img.write_bytes(raw_body[-8000:] if len(raw_body) > 8000 else raw_body)

                db_path = Path.home() / ".personal_agent" / "memory" / "brain.db"
                face_rec = FaceRecognizer(db_path=db_path)
                vision = MultimodalVisionEngine(db_path=db_path)
                social = SocialMediaEngine()

                face_match = face_rec.identify_person(temp_img)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                if face_match.recognized:
                    if face_match.is_owner:
                        result_text = f"👤 **Operator Identified**: Welcome back, {face_match.name}!\n• Match Confidence: {face_match.similarity*100:.1f}%\n• Biometrics: Authenticated."
                    else:
                        result_text = f"👥 **Person Recognized**: {face_match.name} ({face_match.relationship})\n• Match Confidence: {face_match.similarity*100:.1f}%\n• Social graph updated."
                else:
                    filename_lower = temp_img.name.lower()
                    is_food = any(k in filename_lower for k in ["meal", "food", "dish", "chicken", "salad", "diet"])
                    if is_food:
                        record = vision.analyze_food_image(temp_img)
                        result_text = f"🥗 **Nutrition Logged**: {record.food_item}\n• Calories: {record.calories} kcal\n• Protein: {record.protein_g}g | Carbs: {record.carbs_g}g | Fats: {record.fats_g}g"
                    else:
                        enhanced = social.enhance_image(temp_img, filter_style="vibrant", aspect_ratio="1:1")
                        drafts = social.draft_captions("Focused iteration and development.")
                        ig = drafts["instagram"]
                        _, dispatch_msg = social.dispatch_to_device(ig, enhanced)
                        result_text = f"📸 **Photo Enhanced & Social Draft Ready**\n\n• **Saved**: `{enhanced}`\n• **Caption**: \"{ig.caption}\"\n• **Action**: {dispatch_msg}"

                self.wfile.write(json.dumps({"result": result_text}).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        except Exception as e:
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            except Exception:
                pass

    def _send_chunk(self, data: bytes):
        chunk_header = f"{len(data):X}\r\n".encode("utf-8")
        self.wfile.write(chunk_header + data + b"\r\n")
        self.wfile.flush()

    def log_message(self, format, *args):
        return


class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class FloatingCompanionServer:
    def __init__(self, port: int = 14242):
        self.port = port
        self.server = ReusableThreadingServer(("0.0.0.0", self.port), FastUIHandler)
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[✓] Multi-Threaded Streaming UI active at: http://127.0.0.1:{self.port}")

    def update(self, message: Optional[str] = None, state: str = "IDLE", ghost: bool = False):
        if message is not None:
            UI_STATE.message = message
        UI_STATE.state = state
        UI_STATE.ghost = ghost
