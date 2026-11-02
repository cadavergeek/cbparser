import json
import sys
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
import base64

from utils import clean_response, decode_config_value

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def load_config(path: str) -> dict:
    config = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            config[key] = decode_config_value(val) if key == "prompt" else val
    return config


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def send_to_ollama(
    image_base64: str, prompt: str, model: str, ip: str, port: str
) -> dict:
    url = f"http://{ip}:{port}/api/generate"
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
        }
    ).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        return {"error": str(e)}


def run_cli(folder: str):
    config_path = os.path.join(os.path.dirname(__file__), "config.txt")
    if not os.path.isfile(config_path):
        print(f"Error: config file not found at {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    prompt = config.get("prompt", "")
    model = config.get("model", "llava")
    ip = config.get("ip", "127.0.0.1")
    port = config.get("port", "11434")
    fmt = config.get("format", "plain")

    if not prompt:
        print("Error: 'prompt' is not set in config.txt")
        sys.exit(1)

    image_paths = sorted(
        p.resolve()
        for p in Path(folder).iterdir()
        if p.suffix.lower() in IMG_EXTENSIONS
    )

    if not image_paths:
        print(f"No images found in {folder}")
        sys.exit(1)

    results_path = Path(folder) / "results.txt"
    print(f"Model: {model}")
    print(f"Server: {ip}:{port}")
    print(f"Prompt: {prompt}")
    print(f"Images found: {len(image_paths)}")
    print(f"Output: {results_path}")
    print("-" * 50)

    all_results = []
    for img_path in image_paths:
        print(f"Processing: {img_path.name}")
        try:
            b64 = encode_image(str(img_path))
            result = send_to_ollama(b64, prompt, model, ip, port)
            if "error" in result:
                print(f"  Error: {result['error']}")
                all_results.append(f"{img_path.name}\nError: {result['error']}")
            else:
                resp = result.get('response', 'no response')
                if fmt == "plain":
                    resp = clean_response(resp)
                print(f"  Response: {resp}")
                all_results.append(f"{img_path.name}\n{resp}")
        except Exception as e:
            print(f"  Exception: {e}")
            all_results.append(f"{img_path.name}\nException: {e}")
        print("-" * 50)

    results_path.write_text("\n\n".join(all_results), encoding="utf-8")
    print(f"\nResults saved to {results_path}")


def main():
    if len(sys.argv) >= 2:
        folder = sys.argv[1]
        if not os.path.isdir(folder):
            print(f"Error: '{folder}' is not a valid directory.")
            sys.exit(1)
        run_cli(folder)
    else:
        from app import app
        app.run(debug=True)


if __name__ == "__main__":
    main()
