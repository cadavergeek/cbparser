import base64
import json
import os
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from flask import Flask, render_template_string, request, jsonify

from utils import clean_response, decode_config_value, encode_config_value

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Ollama Vision</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
    textarea, input[type=text] { width: 100%; box-sizing: border-box; }
    textarea { min-height: 80px; }
    form { display: flex; flex-direction: column; gap: 1rem; }
    .card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-top: 1rem; }
    .card img { max-width: 100%; max-height: 300px; }
    .response { white-space: pre-wrap; background: #f5f5f5; padding: 0.5rem; border-radius: 4px; }
    label { font-weight: 600; }
    button { padding: 0.5rem 2rem; cursor: pointer; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
    .grid .card { margin: 0; }
    .error { color: #c00; }
    nav { display: flex; gap: 1rem; margin-bottom: 1rem; }
    nav a { text-decoration: none; padding: 0.25rem 0.5rem; }
    nav a.active { font-weight: 700; border-bottom: 2px solid; }
    .dropzone {
      border: 2px dashed #aaa;
      border-radius: 12px;
      padding: 2rem;
      text-align: center;
      cursor: pointer;
      transition: background .2s, border-color .2s;
      outline: none;
    }
    .dropzone.drag-over {
      background: #e3f2fd;
      border-color: #1976d2;
    }
    .dropzone p { margin: .25rem 0; color: #666; }
    .dropzone.drag-over p { color: #1976d2; }
    #previews { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.5rem 0; min-height: 40px; }
    #sendBtn { align-self: flex-start; margin: 0.5rem 0; }
  </style>
</head>
<body>
  <h1>Ollama Vision</h1>
  <nav>
    <a href="/" class="{{ 'active' if tab == 'upload' }}">Upload image</a>
    <a href="/?tab=folder" class="{{ 'active' if tab == 'folder' }}">Scan folder</a>
    <a href="/?tab=settings" class="{{ 'active' if tab == 'settings' }}">Settings</a>
  </nav>

  {% if tab == 'upload' %}
  <label>Prompt</label>
  <textarea id="promptInput">{{ prompt }}</textarea>

  <div id="dropzone"
       tabindex="0"
       class="dropzone"
       ondragover="event.preventDefault(); this.classList.add('drag-over')"
       ondragleave="this.classList.remove('drag-over')"
       ondrop="handleDrop(event)"
       onclick="document.getElementById('fileInput').click()">
    <p>Drag & drop images here</p>
    <p>or click to select files</p>
    <p>or paste (Ctrl+V) from clipboard</p>
    <input type="file" id="fileInput" accept="image/*" multiple hidden
           onchange="handleFiles(this.files)">
  </div>

  <div id="previews"></div>

  <button id="sendBtn" onclick="sendAll()">Send</button>

  <div id="results"></div>

  <details>
    <summary style="cursor:pointer;font-weight:600;margin-top:1rem">Accumulated</summary>
    <textarea id="accumulated" style="width:100%;min-height:120px;font-family:monospace;font-size:13px" readonly></textarea>
    <div style="display:flex;gap:0.5rem;margin-top:0.3rem;flex-wrap:wrap">
      <button onclick="document.getElementById('accumulated').value=''">Clear</button>
      <button onclick="navigator.clipboard.writeText(document.getElementById('accumulated').value)">Copy</button>
      <button onclick="cleanAccumulated()">Format output</button>
    </div>
  </details>

  <script>
    const promptInput = document.getElementById('promptInput');
    const previews = document.getElementById('previews');
    const queue = [];
    const acc = document.getElementById('accumulated');

    function cleanAccumulated() {
      const rows = [];
      for (const block of acc.value.split('\n---\n')) {
        const clean = block
          .replace(/```[a-zA-Z0-9]*\n?/g, '')
          .replace(/`/g, '')
          .replace(/\(Returning\)/gi, '');
        for (let line of clean.split(/\r?\n/)) {
          line = line.trim();
          if (!line) continue;
          if (/^name\s*,/i.test(line)) continue;
          rows.push(line);
        }
      }
      acc.value = rows.join('\n').replace(/,/g, '\t');
    }

    function addToAccumulated(text) {
      if (!text) return;
      acc.value += (acc.value ? '\n---\n' : '') + text;
      acc.scrollTop = acc.scrollHeight;
    }

    function addPreview(src, ext, file) {
      const div = document.createElement('div');
      div.className = 'card';
      div.style.display = 'inline-block';
      div.style.margin = '0.5rem';
      div.style.position = 'relative';
      div.innerHTML = `<img src="${src}" style="max-height:150px;display:block">
        <button onclick="this.parentElement.remove();" style="position:absolute;top:4px;right:4px;padding:2px 8px;font-size:12px;">&times;</button>`;
      previews.appendChild(div);
      queue.push({ src, ext, file, el: div });
    }

    function handleFiles(files) {
      for (const file of files) {
        if (!file.type.startsWith('image/')) continue;
        const reader = new FileReader();
        reader.onload = (e) => {
          const ext = file.type.split('/')[1] || 'png';
          addPreview(e.target.result, ext, file);
        };
        reader.readAsDataURL(file);
      }
    }

    function handleDrop(e) {
      e.preventDefault();
      e.currentTarget.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        handleFiles(e.dataTransfer.files);
      } else if (e.dataTransfer.items.length) {
        for (const item of e.dataTransfer.items) {
          if (item.type === 'text/plain') {
            item.getAsString(async (url) => {
              try {
                const resp = await fetch('/fetch-url', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ url, prompt: promptInput.value })
                });
                const data = await resp.json();
                document.getElementById('results').insertAdjacentHTML('afterbegin', data.html);
                addToAccumulated(data.response);
              } catch {}
            });
          }
        }
      }
    }

    document.addEventListener('paste', (e) => {
      for (const item of e.clipboardData.items) {
        if (item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          const ext = item.type.split('/')[1] || 'png';
          const reader = new FileReader();
          reader.onload = (e) => addPreview(e.target.result, ext, null);
          reader.readAsDataURL(blob);
        }
      }
    });

    async function sendAll() {
      const prompt = promptInput.value;
      for (const item of queue) {
        item.el.querySelector('button').remove();
        item.el.innerHTML += '<div class="response">Sending...</div>';
        try {
          let data;
          if (item.file) {
            const fd = new FormData();
            fd.append('prompt', prompt);
            fd.append('image', item.file);
            const res = await fetch('/analyze', { method: 'POST', body: fd });
            data = await res.json();
          } else {
            const b64 = item.src.split(',')[1];
            const res = await fetch('/analyze-base64', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ prompt, image: b64, ext: item.ext })
            });
            data = await res.json();
          }
          item.el.outerHTML = data.html;
          addToAccumulated(data.response);
        } catch (err) {
          item.el.querySelector('.response').textContent = 'Error: ' + err;
        }
      }
      queue.length = 0;
    }
  </script>
  {% elif tab == 'folder' %}
  <form method="get">
    <input type="hidden" name="tab" value="folder">
    <label>Folder path</label>
    <input type="text" name="path" value="{{ folder_path }}" placeholder="D:\images">
    <label>Prompt (optional, defaults to config.txt)</label>
    <textarea name="prompt">{{ prompt }}</textarea>
    <button type="submit">Analyze folder</button>
  </form>
  {% if results %}
    <div class="grid">
    {% for r in results %}
      <div class="card">
        <img src="data:image/{{ r.ext }};base64,{{ r.b64 }}" alt="">
        <div class="response">{{ r.response }}</div>
      </div>
    {% endfor %}
    </div>
  {% endif %}
  {% if folder_error %}
    <p class="error">{{ folder_error }}</p>
  {% endif %}
  {% elif tab == 'settings' %}
  <form id="settingsForm">
    <label>Prompt</label>
    <textarea name="prompt">{{ prompt }}</textarea>
    <label>Model</label>
    <input type="text" name="model" value="{{ model }}">
    <label>IP</label>
    <input type="text" name="ip" value="{{ ip }}">
    <label>Port</label>
    <input type="text" name="port" value="{{ port }}">
    <label>Format</label>
    <select name="format">
      <option value="plain" {{ 'selected' if fmt == 'plain' else '' }}>Plain (clean markdown)</option>
      <option value="markdown" {{ 'selected' if fmt == 'markdown' else '' }}>Raw markdown</option>
    </select>
    <button type="submit">Save settings</button>
  </form>
  <div id="settingsMsg"></div>
  <script>
    document.getElementById('settingsForm').onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const res = await fetch('/save-config', { method: 'POST', body: fd });
      const data = await res.json();
      document.getElementById('settingsMsg').innerHTML = '<p>' + data.message + '</p>';
    };
  </script>
  {% endif %}
</body>
</html>
"""


def load_config() -> dict:
    cfg = {"prompt": "", "model": "llava", "ip": "127.0.0.1", "port": "11434", "format": "plain"}
    cfg_path = os.path.join(os.path.dirname(__file__), "config.txt")
    if not os.path.isfile(cfg_path):
        return cfg
    with open(cfg_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            cfg[key] = decode_config_value(val) if key == "prompt" else val
    return cfg


def ask_ollama(image_b64: str, prompt: str, model: str, ip: str, port: str, fmt: str = "plain") -> str:
    url = f"http://{ip}:{port}/api/generate"
    payload = json.dumps(
        {"model": model, "prompt": prompt, "images": [image_b64], "stream": False}
    ).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            resp_text = data.get("response", "no response")
            return clean_response(resp_text) if fmt == "plain" else resp_text
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"Ollama error ({e.code}): {body}"
    except URLError as e:
        return f"Connection error: {e.reason}"
    except json.JSONDecodeError:
        return "Error: invalid response from Ollama"
    except Exception as e:
        return f"Error: {e}"


@app.route("/", methods=["GET"])
def index():
    config = load_config()
    tab = request.args.get("tab", "upload")
    folder_path = request.args.get("path", "")
    prompt_override = request.args.get("prompt", "").strip()
    prompt = prompt_override or config.get("prompt", "")
    results = []
    folder_error = ""

    if tab == "folder" and folder_path:
        if not os.path.isdir(folder_path):
            folder_error = f"'{folder_path}' is not a valid directory."
        else:
            images = sorted(Path(folder_path).iterdir())
            for p in images:
                if p.suffix.lower() not in IMG_EXTENSIONS:
                    continue
                b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
                ext = p.suffix.lstrip(".")
                resp = ask_ollama(b64, prompt, config["model"], config["ip"], config["port"], fmt=config.get("format", "plain"))
                results.append({"name": p.name, "ext": ext, "b64": b64, "response": resp})
    return render_template_string(HTML_TEMPLATE, tab=tab, prompt=prompt, folder_path=folder_path, results=results, folder_error=folder_error, model=config.get("model", "llava"), ip=config.get("ip", "127.0.0.1"), port=config.get("port", "11434"), fmt=config.get("format", "plain"))


def _build_result_card(b64: str, ext: str, resp: str) -> str:
    return f"""
    <div class="card">
      <img src="data:image/{ext};base64,{b64}" alt="">
      <div class="response">{resp}</div>
    </div>
    """


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    prompt = request.form.get("prompt", "").strip() or config.get("prompt", "")
    file = request.files.get("image")
    if not file:
        return jsonify({"html": "<p class='error'>No image was uploaded.</p>"})
    b64 = base64.b64encode(file.read()).decode("utf-8")
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    resp = ask_ollama(b64, prompt, config["model"], config["ip"], config["port"], fmt=config.get("format", "plain"))
    return jsonify({"html": _build_result_card(b64, ext, resp), "response": resp})


@app.route("/analyze-base64", methods=["POST"])
def analyze_base64():
    config = load_config()
    data = request.get_json()
    prompt = data.get("prompt", "").strip() or config.get("prompt", "")
    b64 = data.get("image", "")
    ext = data.get("ext", "png")
    if not b64:
        return jsonify({"html": "<p class='error'>No image data.</p>"})
    resp = ask_ollama(b64, prompt, config["model"], config["ip"], config["port"], fmt=config.get("format", "plain"))
    return jsonify({"html": _build_result_card(b64, ext, resp), "response": resp})


@app.route("/fetch-url", methods=["POST"])
def fetch_url():
    config = load_config()
    data = request.get_json()
    url = data.get("url", "")
    prompt = data.get("prompt", "").strip() or config.get("prompt", "")
    if not url:
        return jsonify({"html": "<p class='error'>Empty URL.</p>"})
    try:
        with urlopen(url, timeout=15) as resp:
            raw = resp.read()
        b64 = base64.b64encode(raw).decode("utf-8")
        ctype = resp.headers.get("Content-Type", "image/png")
        ext = ctype.split("/")[-1] if "/" in ctype else "png"
        ollama_resp = ask_ollama(b64, prompt, config["model"], config["ip"], config["port"], fmt=config.get("format", "plain"))
        return jsonify({"html": _build_result_card(b64, ext, ollama_resp), "response": ollama_resp})
    except Exception as e:
        return jsonify({"html": f"<p class='error'>Error fetching URL: {e}</p>"})


@app.route("/save-config", methods=["POST"])
def save_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "config.txt")
    prompt = request.form.get("prompt", "").strip().replace("\r\n", "\n").replace("\r", "\n")
    model = request.form.get("model", "").strip()
    ip = request.form.get("ip", "").strip()
    port = request.form.get("port", "").strip()
    fmt = request.form.get("format", "plain").strip()
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(f"prompt:{encode_config_value(prompt)}\n")
            f.write(f"model:{model}\n")
            f.write(f"ip:{ip}\n")
            f.write(f"port:{port}\n")
            f.write(f"format:{fmt}\n")
        return jsonify({"message": "Settings saved."})
    except Exception as e:
        return jsonify({"message": f"Error saving settings: {e}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
