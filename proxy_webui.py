# -*- coding: utf-8 -*-
# ============================================================
# 缤纷颜色 AI游戏人设改写代理 (proxy_webui.py)
# 版权所有 © 2026 缤纷颜色
#
# 使用条款：
# 1. 本软件免费提供，可个人非商业使用。
# 2. 禁止用于商业牟利；禁止去除本署名后再分发。
# 3. 二次修改/再分发须同样保持免费、非商用，并保留本声明。
# 4. 作者仅对官方渠道发布的原版负责，第三方改版与作者无关。
# 5.本工具仅在上述基准环境测试，其他操作系统、Python、Ollama版本不作兼容性适配，不保障运行，相关问题不提供技术支持。
# 6. 本软件按现状提供，不做任何稳定性担保，使用风险由使用者自行承担。
#
# 环境与依赖：
#基准运行环境：Windows10（专业版），Python 3.13
#第三方依赖：
#Flask 3.1.3
#requests 2.34.2
#安装命令：
#pip install flask requests
#声明：仅在上述基准环境完成测试，其它环境不作兼容性适配与技术支持。
# ============================================================
import os
import re
import json
import time
import ipaddress
import threading
import logging

import requests
from flask import Flask, request, Response, jsonify


LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 4000
UPSTREAM = "http://127.0.0.1:11434/v1"   

DEBUG = True


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "binfenconfig")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")

TEXT_DIR = os.path.join(BASE_DIR, "binfentext")

RULES_FILE = os.path.join(BASE_DIR, "rules.json")

NETWORK_DIR = os.path.join(BASE_DIR, "binfenNetwork")
NETWORK_FILE = os.path.join(NETWORK_DIR, "network.ini")

LEGACY_DEVICE_FILE = os.path.join(BASE_DIR, "devices.json")

LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}


DEFAULT_BLOCK_START = "## 守住世界观"
DEFAULT_BLOCK_END = "## 角色属性"


DEFAULT_CONFIG = {
    "name": "世界书",
    "match_type": "model",          
    "match_value": "eva-ties-14b",
    "scope": "all",                 
    "use_regex": False,
    "enabled": True,
    "block_start": DEFAULT_BLOCK_START,
    "block_end": DEFAULT_BLOCK_END,
    "keep_marks": True,             
    "require_keywords": "",         
    "persona_text": "",
    
    "api_base": "",
    "api_key": "",
    "api_model": "",
    
    "listen_host": "127.0.0.1",
    "listen_port": 4000,
    
    "console_debug": True,
}

app = Flask(__name__)
_lock = threading.RLock()


RUN_HOST = LISTEN_HOST
RUN_PORT = LISTEN_PORT

logging.getLogger("werkzeug").setLevel(logging.ERROR)




_SCALAR_KEYS = ["name", "match_type", "match_value", "scope",
                 "use_regex", "enabled", "block_start", "block_end", "keep_marks", "require_keywords",
                 "api_base", "api_key", "api_model",
                 "listen_host", "listen_port", "console_debug"]



RULE_EXPORT_FIELDS = ["name", "match_type", "scope", "use_regex",
                      "enabled", "block_start", "block_end", "keep_marks", "require_keywords"]

ENV_PRIVATE_KEYS = ["api_base", "api_key", "api_model",
                    "listen_host", "listen_port", "console_debug"]


def _to_bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on", "是")


def parse_ini_text(text):
    cfg = dict(DEFAULT_CONFIG)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        
        if stripped.startswith("persona_text") and "<<<" in stripped:
            block = []
            i += 1
            while i < len(lines) and lines[i].strip() != ">>>":
                block.append(lines[i])
                i += 1
            cfg["persona_text"] = "\n".join(block)
            i += 1  
            continue
        
        if "=" in stripped and not stripped.startswith("#") and not stripped.startswith("["):
            key, _, val = stripped.partition("=")
            key, val = key.strip(), val.strip()
            if key in _SCALAR_KEYS:
                cfg[key] = _to_bool(val) if key in ("use_regex", "enabled", "keep_marks", "console_debug") else val
        i += 1
    return cfg


def render_ini_text(cfg):
    persona = cfg.get("persona_text", "") or ""
    out = ["[worldbook]"]
    for key in _SCALAR_KEYS:
        val = cfg.get(key, DEFAULT_CONFIG.get(key, ""))
        if key in ("use_regex", "enabled", "keep_marks", "console_debug"):
            val = "true" if val else "false"
        out.append(f"{key} = {val}")
    out.append("persona_text = <<<")
    out.extend(persona.splitlines() or [""])
    out.append(">>>")
    return "\n".join(out) + "\n"


def render_rule_ini(rule):
    out = ["[worldbook]"]
    for key in RULE_EXPORT_FIELDS:
        val = rule.get(key, DEFAULT_CONFIG.get(key, ""))
        if key in ("use_regex", "enabled", "keep_marks"):
            val = "true" if val else "false"
        out.append(f"{key} = {val}")
    out.append("persona_text = <<<")
    out.extend((rule.get("persona_text", "") or "").splitlines() or [""])
    out.append(">>>")
    return "\n".join(out) + "\n"


def _ensure_config():
    with _lock:
        if not os.path.isdir(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        if not os.path.exists(CONFIG_FILE):
            _write_config_locked(DEFAULT_CONFIG)


def read_config():
    _ensure_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return parse_ini_text(f.read())
    except Exception:
        return dict(DEFAULT_CONFIG)


def _write_config_locked(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(render_ini_text(cfg))


def write_config(cfg):
    with _lock:
        _write_config_locked(cfg)


def safe_filename(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "世界书"



def load_rules():
    with _lock:
        if not os.path.exists(RULES_FILE):
            return []
        try:
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_rules(rules):
    with _lock:
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)




_last_seen = {}

_RULE_SCALAR = ["name", "match_type", "match_value", "scope", "use_regex",
                "block_start", "block_end", "keep_marks", "require_keywords"]


def _ensure_network():
    with _lock:
        os.makedirs(NETWORK_DIR, exist_ok=True)
        if not os.path.exists(NETWORK_FILE):
            migrated = []
            if os.path.exists(LEGACY_DEVICE_FILE):
                try:
                    with open(LEGACY_DEVICE_FILE, "r", encoding="utf-8") as f:
                        migrated = json.load(f)
                except Exception:
                    migrated = []
            if not isinstance(migrated, list):
                migrated = []
            with open(NETWORK_FILE, "w", encoding="utf-8") as f:
                f.write(render_network_ini(migrated))


def render_network_ini(devices):
    out = []
    for d in devices:
        name = d.get("name") or d.get("ip") or "device"
        out.append(f"[device:{name}]")
        out.append(f"ip = {d.get('ip', '')}")
        out.append(f"enabled = {'true' if d.get('enabled', True) else 'false'}")
        up = d.get("upstream", {}) or {}
        out.append(f"upstream_mode = {up.get('mode', 'local')}")
        out.append(f"upstream_api_base = {up.get('api_base', '')}")
        out.append(f"upstream_api_key = {up.get('api_key', '')}")
        out.append(f"upstream_api_model = {up.get('api_model', '')}")
        for idx, r in enumerate(d.get("rules", []) or [], 1):
            p = f"rule{idx}_"
            out.append(f"{p}name = {r.get('name', '')}")
            out.append(f"{p}enabled = {'true' if r.get('enabled', True) else 'false'}")
            out.append(f"{p}match_type = {r.get('match_type', 'model')}")
            out.append(f"{p}match_value = {r.get('match_value', '')}")
            out.append(f"{p}scope = {r.get('scope', 'all')}")
            out.append(f"{p}use_regex = {'true' if r.get('use_regex', False) else 'false'}")
            out.append(f"{p}block_start = {r.get('block_start', '')}")
            out.append(f"{p}block_end = {r.get('block_end', '')}")
            out.append(f"{p}keep_marks = {'true' if r.get('keep_marks', True) else 'false'}")
            out.append(f"{p}require_keywords = {r.get('require_keywords', '')}")
            out.append(f"{p}persona = <<<")
            out.extend((r.get("persona_text", "") or "").splitlines() or [""])
            out.append(">>>")
        out.append("")
    return "\n".join(out) + "\n"


def _net_rule_by_index(cur, n):
    rules = cur.setdefault("rules", [])
    while len(rules) < n:
        rules.append({"name": "", "enabled": True, "match_type": "model", "match_value": "",
                      "scope": "all", "use_regex": False, "block_start": "", "block_end": "",
                      "keep_marks": True, "require_keywords": "", "persona_text": ""})
    return rules[n - 1]


def parse_network_ini(text):
    devices = []
    cur = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("[device:") and s.endswith("]"):
            cur = {"id": "", "name": s[len("[device:"):-1].strip(), "ip": "", "enabled": True,
                   "upstream": {"mode": "local", "api_base": "", "api_key": "", "api_model": ""},
                   "rules": []}
            devices.append(cur)
            i += 1
            continue
        
        m = re.match(r"(rule\d+)_persona\s*=\s*<<<", s)
        if m and cur is not None:
            block = []
            i += 1
            while i < len(lines) and lines[i].strip() != ">>>":
                block.append(lines[i])
                i += 1
            n = int(re.search(r"\d+", m.group(1)).group())
            _net_rule_by_index(cur, n)["persona_text"] = "\n".join(block)
            i += 1
            continue
        if "=" in s and not s.startswith("#") and not s.startswith("["):
            k, _, v = s.partition("=")
            k, v = k.strip(), v.strip()
            rm = re.match(r"rule(\d+)_(.+)", k)
            if rm and cur is not None:
                rule = _net_rule_by_index(cur, int(rm.group(1)))
                fk = rm.group(2)
                if fk == "enabled":
                    rule["enabled"] = _to_bool(v)
                elif fk == "use_regex":
                    rule["use_regex"] = _to_bool(v)
                elif fk == "keep_marks":
                    rule["keep_marks"] = _to_bool(v)
                elif fk in _RULE_SCALAR:
                    rule[fk] = v
            elif cur is not None:
                if k == "ip":
                    cur["ip"] = v
                elif k == "enabled":
                    cur["enabled"] = _to_bool(v)
                elif k == "upstream_mode":
                    cur["upstream"]["mode"] = "external" if v == "external" else "local"
                elif k == "upstream_api_base":
                    cur["upstream"]["api_base"] = v
                elif k == "upstream_api_key":
                    cur["upstream"]["api_key"] = v
                elif k == "upstream_api_model":
                    cur["upstream"]["api_model"] = v
        i += 1
    return devices


def load_devices():
    _ensure_network()
    try:
        with open(NETWORK_FILE, "r", encoding="utf-8") as f:
            data = parse_network_ini(f.read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_devices(devices):
    _ensure_network()
    with _lock:
        with open(NETWORK_FILE, "w", encoding="utf-8") as f:
            f.write(render_network_ini(devices))


def _ip_matches(pattern, ip):
    pattern = (pattern or "").strip()
    if not pattern or not ip:
        return False
    try:
        if "/" in pattern:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(pattern, strict=False)
        return ipaddress.ip_address(ip) == ipaddress.ip_address(pattern)
    except ValueError:
        return pattern == ip


def find_device(ip):
    ip = (ip or "").strip()
    for d in load_devices():
        if d.get("enabled", True) and _ip_matches(str(d.get("ip", "")), ip):
            return d
    return None



def rule_matches(rule, data):
    mtype = rule.get("match_type", "keyword")
    mvalue = (rule.get("match_value") or "").strip()
    if not mvalue:
        return False

    if mtype == "model":
        
        req_model = str(data.get("model") or "")
        return mvalue.lower() in req_model.lower()

    
    scope = rule.get("scope", "all")  
    use_regex = bool(rule.get("use_regex", False))
    texts = []
    for msg in data.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        if scope == "system" and role != "system":
            continue
        if scope == "user" and role != "user":
            continue
        texts.append(content)
    blob = "\n".join(texts)

    if use_regex:
        try:
            return re.search(mvalue, blob) is not None
        except re.error:
            return False
    
    keywords = [k.strip() for k in re.split(r"[,\u3001;；]", mvalue) if k.strip()]
    return any(k in blob for k in keywords)



def apply_rule_to_messages(rule, data):
    start = rule.get("block_start") or DEFAULT_BLOCK_START
    end = rule.get("block_end") or DEFAULT_BLOCK_END
    persona = rule.get("persona_text") or ""
    if not persona:
        return data, False

    keep_marks = bool(rule.get("keep_marks", True))
    
    block_replacement = f"{start}\n{persona}\n{end}" if keep_marks else persona
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))

    messages = data.get("messages", [])
    changed = False
    for msg in messages:
        if msg.get("role") != "system":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        m = pattern.search(content)
        if m:
            
            required = [k.strip() for k in re.split(r"[,、;；]", rule.get("require_keywords") or "") if k.strip()]
            segment = m.group(0)
            if all(k in segment for k in required):
                msg["content"] = pattern.sub(block_replacement, content, count=1)
                changed = True
        
        break  
    if changed:
        data["messages"] = messages
    return data, changed


_GLOBAL = "__global__"  


def rewrite(data, cfg=_GLOBAL, rules=_GLOBAL):
    hits = []
    replaced = 0

    if cfg is _GLOBAL:
        cfg = read_config()
    if rules is _GLOBAL:
        rules = load_rules()

    
    if cfg and cfg.get("enabled", True):
        try:
            if rule_matches(cfg, data):
                data, ok = apply_rule_to_messages(cfg, data)
                if ok:
                    hits.append(cfg.get("name") or cfg.get("match_value"))
                    replaced += 1
        except Exception as e:
            app.logger.warning("单条配置规则执行失败: %s", e)

    
    for rule in rules or []:
        if not rule.get("enabled", True):
            continue
        try:
            if rule_matches(rule, data):
                data, ok = apply_rule_to_messages(rule, data)
                if ok:
                    hits.append(rule.get("name") or rule.get("match_value"))
                    replaced += 1
        except Exception as e:
            app.logger.warning("规则[%s]执行失败: %s", rule.get("name"), e)
    return data, hits, replaced


def _first_system(messages):
    for m in messages:
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            return m["content"]
    return "(无system消息)"


def _debug_print(tag, text):
    print(f"\n----- {tag} -----")
    print(text)


def _dump_messages(tag, data):
    print(f"\n===== {tag} =====")
    msgs = data.get("messages", [])
    for idx, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content")
        if isinstance(content, str):
            body = content
        else:
            body = json.dumps(content, ensure_ascii=False, indent=2)
        print(f"\n[{idx}] role={role}")
        print(body)



@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    data = request.get_json(force=True, silent=True) or {}
    client_ip = request.remote_addr or ""

    
    if client_ip in LOOPBACK_IPS:
        device = None
    else:
        device = find_device(client_ip)
        if device is None:
            print(f"[拒绝] 未授权设备 {client_ip}，不在设备表中")
            return jsonify({"error": {"message": f"未授权设备 {client_ip}，不在设备表中", "type": "forbidden"}}), 403
        _last_seen[client_ip] = time.time()  

    if DEBUG:
        _dump_messages("改写前·完整原始报文", data)

    
    
    if device is None:
        data, hits, replaced = rewrite(data, cfg=None, rules=load_rules())
        cfg = read_config()
        api_base = (cfg.get("api_base") or "").strip()
        api_key = (cfg.get("api_key") or "").strip()
        api_model = (cfg.get("api_model") or "").strip()
        rule_total = len(load_rules())
        dev_tag = ""
        use_external = bool(api_base and api_key)
    else:
        data, hits, replaced = rewrite(data, cfg=None, rules=device.get("rules", []))
        up = device.get("upstream", {}) or {}
        api_base = (up.get("api_base") or "").strip()
        api_key = (up.get("api_key") or "").strip()
        api_model = (up.get("api_model") or "").strip()
        rule_total = len(device.get("rules", []))
        dev_tag = f" · 设备[{device.get('name') or device.get('ip')}]"
        
        use_external = up.get("mode") == "external" and bool(api_base and api_key)

    if use_external:
        upstream_url = api_base.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if api_model:
            data["model"] = api_model   
    else:
        upstream_url = UPSTREAM + "/chat/completions"
        headers = {"Content-Type": "application/json"}

    if DEBUG:
        print("\n" + "=" * 70)
        print(f"上游={'外援API' if use_external else '本地Ollama'}{dev_tag}  model={data.get('model')}  "
              f"stream={bool(data.get('stream', False))}  命中规则={hits or '无'}")
        if hits:
            _dump_messages("改写后·完整报文", data)
        else:
            print("(无规则命中，原文透传)")

    
    upstream_name = "外援API" if use_external else "本地Ollama"
    if replaced:
        print(f"[请求] {upstream_name}{dev_tag} · 规则列表共 {rule_total} 条 · 成功替换 {replaced} 次 · 命中规则 {', '.join(hits)}")
    else:
        print(f"[请求] {upstream_name}{dev_tag} · 规则列表共 {rule_total} 条 · 无规则命中，原文透传")

    is_stream = bool(data.get("stream", False))

    try:
        upstream_resp = requests.post(
            upstream_url,
            json=data,
            headers=headers,
            stream=is_stream,
            timeout=(10, 300),
        )
    except requests.RequestException as e:
        return jsonify({"error": {"message": f"无法连接上游: {e}", "type": "upstream_error"}}), 502

    if is_stream:
        collected = []
        def gen():
            try:
                for chunk in upstream_resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
                        if DEBUG:
                            _collect_sse_text(chunk, collected)
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n".encode("utf-8")
            finally:
                if DEBUG:
                    _debug_print("模型回复(流式)", "".join(collected))
        return Response(
            gen(),
            status=upstream_resp.status_code,
            content_type=upstream_resp.headers.get("Content-Type", "text/event-stream"),
        )

    
    if DEBUG:
        try:
            body = upstream_resp.json()
            txt = body["choices"][0]["message"]["content"]
            _debug_print("模型回复(非流式)", txt)
        except Exception:
            pass
    return Response(
        upstream_resp.content,
        status=upstream_resp.status_code,
        content_type=upstream_resp.headers.get("Content-Type", "application/json"),
    )


def _collect_sse_text(chunk, out):
    try:
        for line in chunk.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                continue
            obj = json.loads(payload)
            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
            if delta:
                out.append(delta)
    except Exception:
        pass



@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(read_config())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    cfg = request.get_json(force=True, silent=True)
    if not isinstance(cfg, dict):
        return jsonify({"error": "config must be an object"}), 400
    
    merged = read_config()
    for k in ("name", "match_type", "match_value", "scope", "use_regex",
              "enabled", "block_start", "block_end", "keep_marks", "require_keywords", "persona_text",
              "api_base", "api_key", "api_model",
              "listen_host", "listen_port", "console_debug"):
        if k in cfg:
            merged[k] = cfg[k]
    write_config(merged)
    if "console_debug" in merged:
        apply_console_mode(merged.get("console_debug"))
    return jsonify({"ok": True, "file": CONFIG_FILE})


def apply_console_mode(flag):
    global DEBUG
    DEBUG = bool(flag)


@app.route("/api/console-mode", methods=["POST"])
def api_console_mode():
    body = request.get_json(force=True, silent=True) or {}
    flag = bool(body.get("console_debug", True))
    apply_console_mode(flag)
    merged = read_config()
    merged["console_debug"] = flag
    write_config(merged)
    return jsonify({"ok": True, "console_debug": DEBUG})



@app.route("/api/rules", methods=["GET"])
def api_get_rules():
    return jsonify(load_rules())


@app.route("/api/rules", methods=["POST"])
def api_save_rules():
    rules = request.get_json(force=True, silent=True)
    if not isinstance(rules, list):
        return jsonify({"error": "rules must be a list"}), 400
    save_rules(rules)
    return jsonify({"ok": True, "count": len(rules)})



RULE_FIELDS = ["name", "match_type", "match_value", "scope",
               "use_regex", "enabled", "block_start", "block_end", "keep_marks", "require_keywords", "persona_text"]



def _clean_device(d):
    if not isinstance(d, dict):
        return None
    ip = str(d.get("ip", "")).strip()
    if not ip:
        return None
    up = d.get("upstream", {}) or {}
    rules = []
    for r in (d.get("rules") or []):
        if isinstance(r, dict):
            rules.append({k: r.get(k) for k in RULE_FIELDS})
    clean = {
        "id": str(d.get("id") or ""),
        "name": str(d.get("name") or ip),
        "ip": ip,
        "enabled": bool(d.get("enabled", True)),
        "upstream": {
            "mode": "external" if up.get("mode") == "external" else "local",
            "api_base": str(up.get("api_base") or "").strip(),
            "api_key": str(up.get("api_key") or "").strip(),
            "api_model": str(up.get("api_model") or "").strip(),
        },
        "rules": rules,
    }
    if not clean["id"]:
        clean["id"] = "dev_" + ip.replace(".", "_").replace(":", "_")
    return clean


@app.route("/api/devices", methods=["GET"])
def api_get_devices():
    devs = load_devices()
    now = time.time()
    for d in devs:
        last = 0
        for lip, ts in _last_seen.items():
            if _ip_matches(str(d.get("ip", "")), lip):
                last = max(last, ts)
        d["last_seen"] = last
        d["online"] = bool(last and now - last <= 180)  
    return jsonify(devs)


@app.route("/api/devices", methods=["POST"])
def api_save_devices():
    raw = request.get_json(force=True, silent=True)
    if not isinstance(raw, list):
        return jsonify({"error": "devices must be a list"}), 400
    devices = [c for c in (_clean_device(d) for d in raw) if c]
    save_devices(devices)
    return jsonify({"ok": True, "count": len(devices)})


@app.route("/api/import-rules", methods=["POST"])
def api_import_rules():
    payload = request.get_json(force=True, silent=True) or {}
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        return jsonify({"error": "no files"}), 400

    rules = load_rules()
    existing = {(r.get("name") or "").strip() for r in rules}
    imported, skipped, failed = [], [], []

    for item in files:
        fname = (item.get("name") or "").strip()
        text = item.get("content") or ""
        try:
            cfg = parse_ini_text(text)
        except Exception:
            failed.append(fname or "(未命名)")
            continue
        rule = {k: cfg.get(k, DEFAULT_CONFIG.get(k)) for k in RULE_FIELDS}
        
        
        if rule.get("match_type") == "model":
            rule["match_value"] = (read_config().get("match_value") or "").strip()
        else:
            rule["match_value"] = ""
        rname = (rule.get("name") or "").strip() or os.path.splitext(fname)[0]
        rule["name"] = rname
        if not (rule.get("persona_text") or "").strip():
            failed.append(fname or rname)
            continue
        if rname in existing:
            skipped.append(rname)
            continue
        existing.add(rname)
        rules.append(rule)
        imported.append(rname)

    save_rules(rules)
    return jsonify({
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "count": len(rules),
    })



def _ensure_text_dir():
    os.makedirs(TEXT_DIR, exist_ok=True)
    return TEXT_DIR


def _open_folder(path):
    import subprocess, sys as _sys
    try:
        if _sys.platform.startswith("win"):
            os.startfile(path)  
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


@app.route("/api/export", methods=["POST"])
def api_export():
    cfg = request.get_json(force=True, silent=True)
    if not isinstance(cfg, dict):
        return jsonify({"error": "config must be an object"}), 400
    folder = _ensure_text_dir()
    fname = safe_filename(cfg.get("name") or "世界书") + ".ini"
    fpath = os.path.join(folder, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(render_rule_ini(cfg))
    return jsonify({"ok": True, "file": fpath, "name": fname})


@app.route("/api/open-folder", methods=["GET"])
def api_open_folder():
    folder = _ensure_text_dir()
    _open_folder(folder)
    return jsonify({"ok": True, "dir": folder})


@app.route("/api/import", methods=["POST"])
def api_import():
    payload = request.get_json(force=True, silent=True) or {}
    text = payload.get("content", "")
    if not text.strip():
        return jsonify({"error": "empty ini content"}), 400
    parsed = parse_ini_text(text)
    cfg = read_config()  
    for k in RULE_EXPORT_FIELDS + ["persona_text"]:
        if k in parsed:
            cfg[k] = parsed[k]
    write_config(cfg)
    return jsonify({"ok": True, "config": cfg})



INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>缤纷颜色 AI游戏人设改写代理· 规则管理</title>
<style>
  body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f4f5f7;color:#222}
  .wrap{max-width:980px;margin:24px auto;padding:0 16px}
  h1{font-size:20px}
  .card{background:#fff;border:1px solid #e3e5e8;border-radius:10px;padding:16px;margin:12px 0}
  .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
  label{font-size:13px;color:#555;display:block;margin-bottom:4px}
  input,select,textarea{width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:14px}
  textarea{min-height:120px;font-family:monospace;resize:vertical}
  .field{flex:1;min-width:180px}
  button{padding:8px 16px;border:0;border-radius:6px;cursor:pointer;font-size:14px}
  .primary{background:#2563eb;color:#fff}
  .danger{background:#e5484d;color:#fff}
  .ghost{background:#eef0f3}
  .rule-item{border:1px solid #e3e5e8;border-radius:10px;padding:14px;margin:10px 0;background:#fff}
  .tag{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;background:#e8effc;color:#2563eb;margin-right:6px}
  .off{opacity:.5}
  .hint{font-size:12px;color:#888}
  .toast{position:fixed;right:20px;bottom:20px;background:#1f2937;color:#fff;padding:10px 16px;border-radius:8px;display:none}
  /* ===== 美化展示块：左LOGO / 右上B站链接 / 右下QQ群（仅展示，不改任何业务逻辑）===== */
  .about-card{display:flex;gap:18px;align-items:stretch;margin:16px 0;padding:18px;border-radius:14px;border:1px solid #e3e8f5;background:linear-gradient(135deg,#f7f9ff,#eef2fb)}
  .about-logo{flex:0 0 40%;display:flex;align-items:center;justify-content:center;background:#fff;border-radius:12px;overflow:hidden;min-height:220px}
  .about-logo .ph{color:#9aa7bd;font-size:15px;letter-spacing:2px;text-align:center;padding:20px}
  .about-logo img{max-width:100%;max-height:320px;object-fit:contain;border-radius:10px}
  .about-right{flex:1;display:flex;flex-direction:column;gap:14px}
  .about-panel{background:#fff;border:1px solid #eef0f5;border-radius:12px;padding:14px 16px}
  .about-panel h4{margin:0 0 8px;font-size:14px;color:#334155}
  .about-link{display:block;color:#2563eb;text-decoration:none;font-size:14px;line-height:2}
  .about-link:hover{text-decoration:underline}
  .qrow{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 0;font-size:14px;color:#334155;border-bottom:1px dashed #eef0f5}
  .qrow:last-child{border-bottom:0}
  .qnum{font-variant-numeric:tabular-nums}
  .copy-btn{padding:3px 12px;font-size:12px;background:#e8effc;color:#2563eb;border:0;border-radius:6px;cursor:pointer}
  .copy-btn:hover{background:#d8e4fc}
  @media (max-width:720px){.about-card{flex-direction:column}.about-logo{flex:none}}
</style>
</head>
<body>
<div class="wrap">
  <h1>缤纷颜色 AI游戏人设改写代理· 规则管理</h1>
  <div class="hint">当前运行：<b id="runUrl">http://127.0.0.1:4000/v1</b>　｜　配置(重启后生效)：<b id="apiUrl">http://127.0.0.1:4000/v1</b>　｜　上游：本地 Ollama 11434　｜　其余保存即时生效，仅端口需重启</div>

  <div class="card">
    <h3 style="margin:0 0 10px">人设改写配置（保存到 binfenconfig/config.ini）</h3>
    <div class="row">
      <div class="field"><label>规则名称</label><input id="f_name" placeholder="例如：道侣-阿绫"></div>
      <div class="field"><label>匹配方式</label>
        <select id="f_match_type">
          <option value="keyword">消息关键词命中</option>
          <option value="model">按 model 字段命中</option>
        </select>
      </div>
      <div class="field"><label>匹配值（关键词/正则/model名）</label><input id="f_match_value" placeholder="关键词逗号分隔，或开启正则"></div>
    </div>
    <div class="row" style="margin-top:10px">
      <div class="field"><label>匹配范围（仅关键词模式）</label>
        <select id="f_scope">
          <option value="all">全部消息</option>
          <option value="system">仅 system</option>
          <option value="user">仅 user</option>
        </select>
      </div>
      <div class="field" style="max-width:120px"><label>使用正则</label>
        <select id="f_use_regex"><option value="0">否</option><option value="1">是</option></select>
      </div>
      <div class="field" style="max-width:120px"><label>启用</label>
        <select id="f_enabled"><option value="1">启用</option><option value="0">停用</option></select>
      </div>
    </div>
    <div class="row" style="margin-top:10px">
      <div class="field"><label>区间起始标记</label><input id="f_block_start" value="## 守住世界观"></div>
      <div class="field"><label>区间结束标记</label><input id="f_block_end" value="## 角色属性"></div>
      <div class="field" style="max-width:200px"><label>替换方式</label>
        <select id="f_keep_marks">
          <option value="1">保留起止标记（只换中间）</option>
          <option value="0">连起止标记整段替换</option>
        </select>
      </div>
    </div>
    <div class="row" style="margin-top:8px">
      <div class="field"><label>区间内必含关键词（AND：全部出现在区间内才替换，逗号/顿号分隔；留空不校验）</label><input id="f_require_keywords" placeholder="例：郁承锋,承锋"></div>
    </div>
    <div class="hint" style="margin-top:4px">
      <b>保留起止标记</b>：起始标记到结束标记之间的内容被换掉，两句标记本身保留；
      <b>连起止标记整段替换</b>：从起始标记第一个字到结束标记最后一个字（含这两句标记）全部换成下方人设文本。
    </div>
    <div style="margin-top:10px"><label>替换进去的人设文本（起止标记之间的整块换成这段）</label><textarea id="f_persona" placeholder="在此粘贴该角色的世界观/人设正文"></textarea></div>

    <div class="card" style="margin-top:14px;background:#fafbfc">
      <h3 style="margin:0 0 10px;font-size:15px">外援API（DeepSeek等OpenAI兼容接口，留空则走本地Ollama）</h3>
      <div class="row">
        <div class="field"><label>接口地址 api_base</label><input id="f_api_base" placeholder="如 https://api.deepseek.com/v1"></div>
        <div class="field"><label>API密钥 api_key</label><input id="f_api_key" type="password" placeholder="sk-..."></div>
        <div class="field" style="max-width:220px"><label>外援模型名 api_model</label><input id="f_api_model" placeholder="如 deepseek-chat"></div>
      </div>
      <div class="hint" style="margin-top:6px">填好接口地址+密钥即走外援（自动带 Bearer 鉴权、用上面的模型名覆盖）；两项都留空则回退本地 Ollama。此区块随“保存配置”写入 config.ini。</div>
    </div>

    <div class="card" style="margin-top:14px;background:#fafbfc">
      <h3 style="margin:0 0 10px;font-size:15px">修改服务地址 / 端口（端口被占用就在这里改，保存后重启生效）</h3>
      <div class="row">
        <div class="field" style="max-width:240px"><label>监听地址（默认127.0.0.1，仅本机；局域网共用填0.0.0.0）</label><input id="f_listen_host" placeholder="127.0.0.1"></div>
        <div class="field" style="max-width:180px"><label>监听端口（如4000，被占用就换4001等）</label><input id="f_listen_port" placeholder="4000"></div>
      </div>
      <div class="hint" style="margin-top:6px">填好后点<b>保存配置</b>，再<b>重启程序</b>生效；临时换端口也可命令行：<code>python proxy_webui.py 127.0.0.1 4001</code>（命令行优先）。</div>
    </div>

    <div class="card" style="margin-top:14px;background:#fafbfc">
      <h3 style="margin:0 0 10px;font-size:15px">控制台输出模式（即时切换，自动记住，无需重启）</h3>
      <div class="row" style="align-items:center">
        <div class="field" style="max-width:320px">
          <select id="f_console_debug" onchange="switchConsoleMode()">
            <option value="1">详细调试（打印改写前后报文 + 模型回复）</option>
            <option value="0">精简（只出每轮汇总行 + 连接错误）</option>
          </select>
        </div>
        <div class="hint" style="margin:0 0 0 10px">切换立即生效并写入 config.ini，下次启动沿用。</div>
      </div>
    </div>

    <div class="row" style="margin-top:10px">
      <button class="primary" onclick="upsert()" id="ruleBtn">保存规则（添加/更新）</button>
      <button class="ghost" onclick="saveConfig()">保存配置</button>
      <button class="ghost" onclick="clearForm()">清空表单</button>
      <button class="ghost" onclick="reloadConfig()">重新读取 config.ini</button>
      <button class="ghost" onclick="exportConfig()">导出为ini</button>
      <button class="ghost" onclick="importConfig()">导入ini（覆盖当前配置）</button>
      <button class="ghost" onclick="batchImportRules()">批量导入规则INI（多选）</button>
      <input type="file" id="fileInput" accept=".ini" style="display:none" onchange="onFileChosen(event)">
      <input type="file" id="batchFileInput" accept=".ini" multiple style="display:none" onchange="onBatchChosen(event)">
    </div>
    <div class="hint" style="margin-top:6px;line-height:1.8">
      <b>保存规则（添加/更新）</b>=加入/更新下方“现有规则”列表(rules.json)；
      <b>保存配置</b>=写入 binfenconfig/config.ini 当前生效配置；
      <b>导出为ini</b>=把当前界面配置存为 binfentext/&lt;规则名&gt;.ini；
      <b>导入ini</b>=选一个 ini 覆盖当前配置(config.ini)；
      <b>批量导入规则INI</b>=多选 ini，按名称批量合并进下方规则列表(rules.json)，同名跳过、缺人设文本判无效。
    </div>
  </div>

  <!-- ===== 美化展示块（纯展示，不参与任何业务逻辑）=====
       左侧：LOGO 位，可替换为 917×570 图片，块内等比例显示、四周可留白；
       右上：B站主页 / 直播间，文字即链接，新标签页跳转，不显示裸网址；
       右下：5个QQ群号，点“复制”把群号写入剪贴板，不做跳转。
       以下网址/群号为展示素材，设计要求仅记录在此注释，不在界面上显示说明文字。 -->
  <div class="about-card">
    <div class="about-logo">
      <!-- 赞助/二维码图：原字节 base64 内嵌，勿二次重压缩以免伤扫码 -->
      <img src="data:image/jpeg;base64,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AAAAAAAAAFRvcCBVbnRGI1JsdAAAAAAAAAAAAAAAAFNjbCBVbnRGI1ByY0BZAAAAAAAAAAAAEGNyb3BXaGVuUHJpbnRpbmdib29sAAAAAA5jcm9wUmVjdEJvdHRvbWxvbmcAAAAAAAAADGNyb3BSZWN0TGVmdGxvbmcAAAAAAAAADWNyb3BSZWN0UmlnaHRsb25nAAAAAAAAAAtjcm9wUmVjdFRvcGxvbmcAAAAAADhCSU0D7QAAAAAAEABIAAAAAQACAEgAAAABAAI4QklNBCYAAAAAAA4AAAAAAAAAAAAAP4AAADhCSU0D8gAAAAAACgAA////////AAA4QklNBA0AAAAAAAQAAABaOEJJTQQZAAAAAAAEAAAAHjhCSU0D8wAAAAAACQAAAAAAAAAAAQA4QklNJxAAAAAAAAoAAQAAAAAAAAACOEJJTQP1AAAAAABIAC9mZgABAGxmZgAGAAAAAAABAC9mZgABAKGZmgAGAAAAAAABADIAAAABAFoAAAAGAAAAAAABADUAAAABAC0AAAAGAAAAAAABOEJJTQP4AAAAAABwAAD/////////////////////////////A+gAAAAA/////////////////////////////wPoAAAAAP////////////////////////////8D6AAAAAD/////////////////////////////A+gAADhCSU0EAAAAAAAAAgAGOEJJTQQCAAAAAAAOAAAAAAAAAAAAAAAAAAA4QklNBDAAAAAAAAcBAQEBAQEBADhCSU0ELQAAAAAAAgAAOEJJTQQIAAAAAAAQAAAAAQAAAkAAAAJAAAAAADhCSU0ERAAAAAAAEAAAAAIAAAJAAAACQAAAAAA4QklNBB4AAAAAAAQAAAAAOEJJTQQaAAAAAAM9AAAABgAAAAAAAAAAAAACOgAAA5UAAAAEW51bnVb+ckcAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAA5UAAAI6AAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAEAAAAAAABudWxsAAAAAgAAAAZib3VuZHNPYmpjAAAAAQAAAAAAAFJjdDEAAAAEAAAAAFRvcCBsb25nAAAAAAAAAABMZWZ0bG9uZwAAAAAAAAAAQnRvbWxvbmcAAAI6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OS0xMjo0MDoyNyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczpkYz0iaHR0cDovL3B1cmwub3JnL2RjL2VsZW1lbnRzLzEuMS8iIHhtbG5zOnBob3Rvc2hvcD0iaHR0cDovL25zLmFkb2JlLmNvbS9waG90b3Nob3AvMS4wLyIgeG1sbnM6eG1wTU09Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iIHhtbG5zOnN0RXZ0PSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VFdmVudCMiIHhtbG5zOnN0UmVmPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VSZWYjIiB4bXA6Q3JlYXRvclRvb2w9IkFkb2JlIFBob3Rvc2hvcCAyNS41IChXaW5kb3dzKSIgeG1wOkNyZWF0ZURhdGU9IjIwMjYtMTAtMThUMjM6MjI6NDArMDg6MDAiIHhtcDpNb2RpZnlEYXRlPSIyMDI2LTEwLTIzVDEzOjMyOjQxKzA4OjAwIiB4bXA6TWV0YWRhdGFEYXRlPSIyMDI2LTEwLTIzVDEzOjMyOjQxKzA4OjAwIiBkYzpmb3JtYXQ9ImltYWdlL2pwZWciIHBob3Rvc2hvcDpDb2xvck1vZGU9IjMiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6MTMzNzRhNTEtYmY4OS03ODQyLTk0NGItZTBjNjY0Mjk5YmQ3IiB4bXBNTTpEb2N1bWVudElEPSJhZG9iZTpkb2NpZDpwaG90b3Nob3A6YTIxMjQ2NWUtYjU0NC04NzQ2LThmYTctOTFiOWFjYjc5Mzk2IiB4bXBNTTpPcmlnaW5hbERvY3VtZW50SUQ9InhtcC5kaWQ6ZDE4NTEzYTktM2U3Yi1kNTRmLTkzNmEtOTQwM2I5MTkzNTNhIj4gPHhtcE1NOkhpc3Rvcnk+IDxyZGY6U2VxPiA8cmRmOmxpIHN0RXZ0OmFjdGlvbj0iY3JlYXRlZCIgc3RFdnQ6aW5zdGFuY2VJRD0ieG1wLmlpZDpkMTg1MTNhOS0zZTdiLWQ1NGYtOTM2YS05NDAzYjkxOTM1M2EiIHN0RXZ0OndoZW49IjIwMjYtMTAtMThUMjM6MjI6NDArMDg6MDAiIHN0RXZ0OnNvZnR3YXJlQWdlbnQ9IkFkb2JlIFBob3Rvc2hvcCAyNS41IChXaW5kb3dzKSIvPiA8cmRmOmxpIHN0RXZ0OmFjdGlvbj0ic2F2ZWQiIHN0RXZ0Omluc3RhbmNlSUQ9InhtcC5paWQ6MmI4MmJkOTItMTQ2Yi05NTRmLTk2NjEtYjRlNGRmZWZhZDhjIiBzdEV2dDp3aGVuPSIyMDI2LTEwLTIzVDEzOjMyOjQxKzA4OjAwIiBzdEV2dDpzb2Z0d2FyZUFnZW50PSJBZG9iZSBQaG90b3Nob3AgMjUuNSAoV2luZG93cykiIHN0RXZ0OmNoYW5nZWQ9Ii8iLz4gPHJkZjpsaSBzdEV2dDphY3Rpb249ImNvbnZlcnRlZCIgc3RFdnQ6cGFyYW1ldGVycz0iZnJvbSBhcHBsaWNhdGlvbi92bmQuYWRvYmUucGhvdG9zaG9wIHRvIGltYWdlL2pwZWciLz4gPHJkZjpsaSBzdEV2dDphY3Rpb249ImRlcml2ZWQiIHN0RXZ0OnBhcmFtZXRlcnM9ImNvbnZlcnRlZCBmcm9tIGFwcGxpY2F0aW9uL3ZuZC5hZG9iZS5waG90b3Nob3AgdG8gaW1hZ2UvanBlZyIvPiA8cmRmOmxpIHN0RXZ0OmFjdGlvbj0ic2F2ZWQiIHN0RXZ0Omluc3RhbmNlSUQ9InhtcC5paWQ6MTMzNzRhNTEtYmY4OS03ODQyLTk0NGItZTBjNjY0Mjk5YmQ3IiBzdEV2dDp3aGVuPSIyMDI2LTEwLTIzVDEzOjMyOjQxKzA4OjAwIiBzdEV2dDpzb2Z0d2FyZUFnZW50PSJBZG9iZSBQaG90b3Nob3AgMjUuNSAoV2luZG93cykiIHN0RXZ0OmNoYW5nZWQ9Ii8iLz4gPC9yZGY6U2VxPiA8L3htcE1NOkhpc3Rvcnk+IDx4bXBNTTpEZXJpdmVkRnJvbSBzdFJlZjppbnN0YW5jZUlEPSJ4bXAuaWlkOjJiODJiZDkyLTE0NmItOTU0Zi05NjYxLWI0ZTRkZmVmYWQ4YyIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDpkMTg1MTNhOS0zZTdiLWQ1NGYtOTM2YS05NDAzYjkxOTM1M2EiIHN0UmVmOm9yaWdpbmFsRG9jdW1lbnRJRD0ieG1wLmRpZDpkMTg1MTNhOS0zZTdiLWQ1NGYtOTM2YS05NDAzYjkxOTM1M2EiLz4gPC9yZGY6RGVzY3JpcHRpb24+IDwvcmRmOlJERj4gPC94OnhtcG1ldGE+ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgPD94cGFja2V0IGVuZD0idyI/Pv/uAA5BZG9iZQBkAAAAAAH/2wCEAAYEBAQFBAYFBQYJBgUGCQsIBgYICwwKCgsKCgwQDAwMDAwMEAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwBBwcHDQwNGBAQGBQODg4UFA4ODg4UEQwMDAwMEREMDAwMDAwRDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDP/AABEIAjoDlQMBEQACEQEDEQH/3QAEAHP/xAGiAAAABwEBAQEBAAAAAAAAAAAEBQMCBgEABwgJCgsBAAICAwEBAQEBAAAAAAAAAAEAAgMEBQYHCAkKCxAAAgEDAwIEAgYHAwQCBgJzAQIDEQQABSESMUFRBhNhInGBFDKRoQcVsUIjwVLR4TMWYvAkcoLxJUM0U5KismNzwjVEJ5OjszYXVGR0w9LiCCaDCQoYGYSURUaktFbTVSga8uPzxNTk9GV1hZWltcXV5fVmdoaWprbG1ub2N0dXZ3eHl6e3x9fn9zhIWGh4iJiouMjY6PgpOUlZaXmJmam5ydnp+So6SlpqeoqaqrrK2ur6EQACAgECAwUFBAUGBAgD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MRBq2KvRfXGKvGvNv/OLv5feafMmoeYNR1HVYrzUpjPPHbzWyxBiAPhVrd27d3bFUoP/ADhx+V//AFdNb/5H2n/ZLir3OxjjsrG3s42LR20SQoWpUiNQorQKK7dlxV5P54/5xq8h+cfNN95k1S/1SG+1Ao00dtNbrEDHEsS8RJbyN9lP58VQGgf84qfl1oevabrdpqOrvd6ZdQ3tuks1qYzJbyLKgcLbISvJBy4suKvaxcAACuKrhcDFULqtpBqml3mmzsywXsElvKyEBwkqFG4kgitDirw//oTb8rf+rprf/I+0/wCyXFXf9Cbfld/1dNb/AOR9p/2S4q0f+cN/yu/6umt/8j7T/slxV7F5Q8u2HlXy1YeXtPlllstOj9GCS4YNKVqT8RVUWu/7KriqdCfFVwmGKr1lxVUD4qvDYquxVvFXYq//1PVOKuxVxxVaTiqk70xVDyS0xVDSXHviqg1z74qpm6HjirYuh44quF174q39a98VaN174qsN2PHFVpux44qt+uDxxV31weOKu+uDxxVr64PHFWvrg8cVaN6PHFVv10eOKu+ujxxVcL0eOKrheDxxVeLseOKt/Wx44q762PHFVpux44q19cHjirYux44qqJdDxxVER3HviqJjmr3xVEI+KqynFV2KuxVaWxVSZ6YqovNTFUO9xTviqg1z74qpm6HjirX1r3xVcLr3xVv6174q0br3xVYbseOKrDdjxxVb9cHjirYvB44qqC7Hjiq8XXvirf1r3xVxuvfFVpuh44qsN2PHFWvrY8cVa+tjxxV31seOKu+t++KtG7HjirX1weOKtfXB44qvF2PHFVVLr3xVER3HviqJjm98VV0kxVVDYqvBxV2KrScVU2emKqDy++Kod7j3xVDvc++KqRux44q19bHjirYux44quF0PHFXfWvfFWjdDxxVabseOKrfrY8cVd9bHjiq4XY8cVXi6Hjirf1r3xV31r3xVxuvfFWjdDxxVr6174q76174q76174q760PHFVpux44qtN2PHFVpvF8cVcLweOKrhdjxxVcLseOKrvrQ8cVd9aHjiq03Y8cVa+tjxxVsXQ8cVVUuffFVeOf3xVExy1xVEK2KqgOKrxirsVf/V9U4q7FWjiqk7YqhpZKYqgZ56d8VS65vAoO+Kt+XtIs9XsJb68EjGaeQWzLLInGOOkewRgPto7Yqk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" alt="自愿赞助支持创作">
    </div>
    <div class="about-right">
      <div class="about-panel">
        <h4>关注</h4>
        <a class="about-link" href="https://space.bilibili.com/365816484" target="_blank" rel="noopener">缤纷颜色 · B站主页</a>
        <a class="about-link" href="http://live.bilibili.com/23286112" target="_blank" rel="noopener">缤纷颜色 · B站直播间</a>
      </div>
      <div class="about-panel">
        <h4>AI游戏爱好者交流群（点按钮复制群号）</h4>
        <div class="qrow"><span>1群　<span class="qnum">1126053841</span></span><button class="copy-btn" onclick="copyGroup('1126053841')">复制</button></div>
        <div class="qrow"><span>2群　<span class="qnum">737151796</span></span><button class="copy-btn" onclick="copyGroup('737151796')">复制</button></div>
        <div class="qrow"><span>3群　<span class="qnum">1131113766</span></span><button class="copy-btn" onclick="copyGroup('1131113766')">复制</button></div>
        <div class="qrow"><span>4群　<span class="qnum">1131117969</span></span><button class="copy-btn" onclick="copyGroup('1131117969')">复制</button></div>
        <div class="qrow"><span>5群　<span class="qnum">1131114304</span></span><button class="copy-btn" onclick="copyGroup('1131114304')">复制</button></div>
      </div>
    </div>
  </div>

  <h3 style="margin-top:18px">现有规则（rules.json，点“编辑”回填表单，删除即时生效）</h3>
  <div id="list"></div>

  <div class="card" style="margin-top:18px">
    <h3 style="margin:0 0 8px;font-size:15px">局域网设备管理（按 IP/网段独立上游 + 专属规则；未登记自动 403 拒绝）</h3>
    <div class="hint" style="margin-bottom:10px">本机 127.0.0.1 永远豁免、走全局配置；这里只登记局域网其他设备。IP 填单台精确地址，或填 CIDR 网段（如 192.168.1.0/24）批量放行整段。配置独立保存在 binfenNetwork/network.ini；在线状态为被动探测（3 分钟内有请求算在线）。建议在路由器给设备绑固定 IP，避免 DHCP 变动。</div>
    <div class="row" style="margin-bottom:10px"><button class="primary" onclick="openDeviceEditor(-1)">+ 添加设备</button></div>
    <div id="deviceList"></div>

    <div id="deviceEditor" style="display:none;border:1px dashed #c5cdd9;border-radius:10px;padding:14px;margin-top:12px;background:#fafbfc">
      <div class="row">
        <div class="field"><label>设备名称</label><input id="d_name" placeholder="如：客厅电视"></div>
        <div class="field" style="max-width:240px"><label>设备 IP 或网段（单IP精确 / CIDR批量放行）</label><input id="d_ip" placeholder="如 192.168.1.20 或 192.168.1.0/24"></div>
        <div class="field" style="max-width:140px"><label>启用</label>
          <select id="d_enabled"><option value="1">启用</option><option value="0">停用</option></select>
        </div>
      </div>
      <div class="row" style="margin-top:10px">
        <div class="field" style="max-width:220px"><label>上游模式</label>
          <select id="d_upmode" onchange="onUpModeChange()">
            <option value="local">本地 Ollama</option>
            <option value="external">外援 API（DeepSeek 等）</option>
          </select>
        </div>
      </div>
      <div id="d_ext" style="margin-top:10px">
        <div class="row">
          <div class="field"><label>外援接口地址 api_base</label><input id="d_api_base" placeholder="https://api.deepseek.com/v1"></div>
          <div class="field"><label>API 密钥 api_key</label><input id="d_api_key" type="password" placeholder="sk-..."></div>
          <div class="field" style="max-width:200px"><label>外援模型名 api_model</label><input id="d_api_model" placeholder="deepseek-chat"></div>
        </div>
      </div>

      <div style="margin-top:14px">
        <div class="row" style="margin-bottom:6px"><b style="flex:1">该设备专属规则</b><button class="ghost" onclick="addDevRule()">+ 添加规则</button></div>
        <div id="devRules"></div>
      </div>

      <div class="row" style="margin-top:14px">
        <button class="primary" onclick="saveDevice()">保存设备</button>
        <button class="ghost" onclick="closeDeviceEditor()">取消</button>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
function fill(cfg){
  document.getElementById('f_name').value = cfg.name||'';
  document.getElementById('f_match_type').value = cfg.match_type||'model';
  document.getElementById('f_match_value').value = cfg.match_value||'';
  document.getElementById('f_scope').value = cfg.scope||'all';
  document.getElementById('f_use_regex').value = cfg.use_regex?'1':'0';
  document.getElementById('f_enabled').value = cfg.enabled===false?'0':'1';
  document.getElementById('f_block_start').value = cfg.block_start||'## 守住世界观';
  document.getElementById('f_block_end').value = cfg.block_end||'## 角色属性';
  document.getElementById('f_keep_marks').value = cfg.keep_marks===false?'0':'1';
  document.getElementById('f_require_keywords').value = cfg.require_keywords||'';
  document.getElementById('f_persona').value = cfg.persona_text||'';
  document.getElementById('f_api_base').value = cfg.api_base||'';
  document.getElementById('f_api_key').value = cfg.api_key||'';
  document.getElementById('f_api_model').value = cfg.api_model||'';
  document.getElementById('f_listen_host').value = cfg.listen_host||'127.0.0.1';
  document.getElementById('f_listen_port').value = cfg.listen_port||4000;
  document.getElementById('f_console_debug').value = cfg.console_debug===false?'0':'1';
}

function collect(){
  return {
    name: document.getElementById('f_name').value.trim(),
    match_type: document.getElementById('f_match_type').value,
    match_value: document.getElementById('f_match_value').value,
    scope: document.getElementById('f_scope').value,
    use_regex: document.getElementById('f_use_regex').value==='1',
    enabled: document.getElementById('f_enabled').value==='1',
    block_start: document.getElementById('f_block_start').value || '## 守住世界观',
    block_end: document.getElementById('f_block_end').value || '## 角色属性',
    keep_marks: document.getElementById('f_keep_marks').value==='1',
    require_keywords: document.getElementById('f_require_keywords').value.trim(),
    persona_text: document.getElementById('f_persona').value,
    api_base: document.getElementById('f_api_base').value.trim(),
    api_key: document.getElementById('f_api_key').value.trim(),
    api_model: document.getElementById('f_api_model').value.trim(),
    listen_host: document.getElementById('f_listen_host').value.trim(),
    listen_port: document.getElementById('f_listen_port').value.trim()
  };
}

async function switchConsoleMode(){
  const flag = document.getElementById('f_console_debug').value==='1';
  const r = await fetch('/api/console-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({console_debug:flag})});
  const j = await r.json();
  if(j.ok){ toast(flag?'已切换：详细调试':'已切换：精简输出'); } else { alert('切换失败'); }
}

async function reloadConfig(){
  const [rc, sc] = await Promise.all([fetch('/api/config'), fetch('/api/server')]);
  const cfg = await rc.json();
  const srv = await sc.json();
  fill(cfg);
  document.getElementById('apiUrl').textContent = `http://${cfg.listen_host||'127.0.0.1'}:${cfg.listen_port||4000}/v1`;
  document.getElementById('runUrl').textContent = srv.api_url;
}

async function saveConfig(){
  const cfg = collect();
  const old = await (await fetch('/api/server')).json();
  // 保存配置不强制人设/匹配值，允许只配外援API或仅调整参数
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  const newHost = cfg.listen_host||'127.0.0.1';
  const newPort = cfg.listen_port||4000;
  if(String(old.port)!==String(newPort) || old.host!==newHost){
    alert(`地址/端口已改为 http://${newHost}:${newPort}/v1\n需要重启程序后才生效；重启后请用这个新地址打开网页。`);
  } else {
    toast('已保存到 config.ini 并即时生效');
  }
  reloadConfig();
}

async function exportConfig(){
  const cfg = collect();
  if(!cfg.name.trim()){ alert('请先填写规则名称（作为导出文件名）'); return; }
  const r = await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  const j = await r.json();
  if(j.ok){ toast('已导出：' + j.name); } else { alert('导出失败'); }
}

async function importConfig(){
  // 先确保 binfentext 存在并弹出系统文件夹窗口，再唤起文件选择框
  await fetch('/api/open-folder');
  document.getElementById('fileInput').value = '';
  document.getElementById('fileInput').click();
}

function onFileChosen(ev){
  const file = ev.target.files[0];
  if(!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    const r = await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:reader.result})});
    const j = await r.json();
    if(j.ok){ fill(j.config); toast('已导入并覆盖当前配置'); }
    else { alert('导入失败：'+(j.error||'未知错误')); }
  };
  reader.readAsText(file, 'utf-8');
}

// ============ 批量导入多个 ini → 合并进 rules.json ============
async function batchImportRules(){
  await fetch('/api/open-folder');
  const bi = document.getElementById('batchFileInput');
  bi.value = '';
  bi.click();
}

function onBatchChosen(ev){
  const list = Array.from(ev.target.files || []);
  if(!list.length) return;
  Promise.all(list.map(f => new Promise(res => {
    const rd = new FileReader();
    rd.onload = () => res({name: f.name, content: rd.result});
    rd.onerror = () => res({name: f.name, content: ''});
    rd.readAsText(f, 'utf-8');
  }))).then(async (files) => {
    const r = await fetch('/api/import-rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({files})});
    const j = await r.json();
    if(!j.ok){ alert('批量导入失败：'+(j.error||'未知错误')); return; }
    await loadRules();
    let msg = `成功导入 ${j.imported.length} 条规则`;
    if(j.skipped && j.skipped.length) msg += `\n同名跳过 ${j.skipped.length} 条：${j.skipped.join('、')}`;
    if(j.failed && j.failed.length) msg += `\n无效/缺人设 ${j.failed.length} 条：${j.failed.join('、')}`;
    alert(msg);
    toast(`批量导入完成：成功${j.imported.length} 跳过${(j.skipped||[]).length} 无效${(j.failed||[]).length}`);
  });
}

// ============ 多规则列表 rules.json（保存规则 添加/更新） ============
let rules = [];
let editingIdx = -1;

async function loadRules(){
  const r = await fetch('/api/rules');
  rules = await r.json();
  renderRules();
}

function renderRules(){
  const box = document.getElementById('list');
  box.innerHTML = '';
  rules.forEach((rule, i) => {
    const div = document.createElement('div');
    div.className = 'rule-item' + (rule.enabled===false?' off':'');
    const mt = rule.match_type==='model' ? 'model='+rule.match_value : '关键词('+rule.scope+'):'+rule.match_value;
    div.innerHTML = `
      <div class="row">
        <b style="flex:1">${rule.name||'(未命名)'} ${rule.enabled===false?'<span class=tag>已停用</span>':''}</b>
        <button class="ghost" onclick="editRule(${i})">编辑</button>
        <button class="danger" onclick="removeRule(${i})">删除</button>
      </div>
      <div class="hint" style="margin-top:6px"><span class="tag">${mt}</span>正则:${rule.use_regex?'是':'否'}　替换:${rule.keep_marks===false?'连标记整段替换':'保留标记'}　区间:${rule.block_start} … ${rule.block_end}${rule.require_keywords?`　必含:${rule.require_keywords}`:''}</div>
      <div class="hint" style="margin-top:6px;white-space:pre-wrap">${(rule.persona_text||'').slice(0,200)}</div>
    `;
    box.appendChild(div);
  });
}

function upsert(){
  const r = collect();
  if(!r.match_value.trim()){ alert('请填写匹配值（model名 或 关键词/正则）'); return; }
  if(!r.persona_text.trim()){ alert('请填写要替换进去的人设文本'); return; }
  if(editingIdx>=0){ rules[editingIdx] = r; } else { rules.push(r); }
  saveRules();
}

function editRule(i){
  editingIdx = i;
  const r = rules[i];
  fill(r);
  document.getElementById('ruleBtn').textContent = '保存修改';
  window.scrollTo({top:0,behavior:'smooth'});
}

function removeRule(i){ rules.splice(i,1); saveRules(); }

function clearForm(){
  editingIdx=-1;
  ['f_name','f_match_value','f_persona'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('ruleBtn').textContent='保存规则（添加/更新）';
}

async function saveRules(){
  editingIdx=-1;
  document.getElementById('ruleBtn').textContent='保存规则（添加/更新）';
  await fetch('/api/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rules)});
  await loadRules();
  toast('规则已保存并即时生效');
}

// ============ 局域网设备管理（按IP独立上游+专属规则） ============
let devices=[];
let devDraft=null;
let devEditingIdx=-1;

async function loadDevices(){
  const r=await fetch('/api/devices');
  devices=await r.json();
  renderDevices();
}

function fmtAgo(ts){
  if(!ts) return '从未连接';
  const s=Math.floor(Date.now()/1000-ts);
  if(s<60) return '刚刚';
  if(s<3600) return Math.floor(s/60)+' 分钟前';
  if(s<86400) return Math.floor(s/3600)+' 小时前';
  return Math.floor(s/86400)+' 天前';
}

function renderDevices(){
  const box=document.getElementById('deviceList');
  box.innerHTML='';
  devices.forEach((d,i)=>{
    const up=d.upstream||{};
    const upTxt=up.mode==='external'?('外援:'+(up.api_model||up.api_base||'')):'本地Ollama';
    const status=d.online
      ? '<span style="color:#16a34a">● 在线</span>'
      : '<span style="color:#aaa">○ 离线</span>';
    const div=document.createElement('div');
    div.className='rule-item'+(d.enabled===false?' off':'');
    div.innerHTML=`
      <div class="row">
        <b style="flex:1">${d.name||d.ip} ${d.enabled===false?'<span class=tag>已停用</span>':''}</b>
        <span class="hint">${status}　${fmtAgo(d.last_seen)}</span>
        <button class="ghost" onclick="toggleDevice(${i})">${d.enabled===false?'启用':'停用'}</button>
        <button class="ghost" onclick="openDeviceEditor(${i})">编辑</button>
        <button class="danger" onclick="removeDevice(${i})">删除</button>
      </div>
      <div class="hint" style="margin-top:6px">IP/网段：${d.ip}　上游：${upTxt}　专属规则：${(d.rules||[]).length} 条</div>`;
    box.appendChild(div);
  });
}

function onUpModeChange(){
  const mode=document.getElementById('d_upmode').value;
  document.getElementById('d_ext').style.display=mode==='external'?'block':'none';
}

function openDeviceEditor(i){
  devEditingIdx=i;
  if(i>=0){
    devDraft=JSON.parse(JSON.stringify(devices[i]));
  }else{
    devDraft={id:'',name:'',ip:'',enabled:true,upstream:{mode:'local',api_base:'',api_key:'',api_model:''},rules:[]};
  }
  document.getElementById('d_name').value=devDraft.name||'';
  document.getElementById('d_ip').value=devDraft.ip||'';
  document.getElementById('d_enabled').value=devDraft.enabled===false?'0':'1';
  document.getElementById('d_upmode').value=(devDraft.upstream&&devDraft.upstream.mode)==='external'?'external':'local';
  document.getElementById('d_api_base').value=(devDraft.upstream&&devDraft.upstream.api_base)||'';
  document.getElementById('d_api_key').value=(devDraft.upstream&&devDraft.upstream.api_key)||'';
  document.getElementById('d_api_model').value=(devDraft.upstream&&devDraft.upstream.api_model)||'';
  onUpModeChange();
  renderDevRules();
  document.getElementById('deviceEditor').style.display='block';
  window.scrollTo({top:document.getElementById('deviceEditor').offsetTop-20,behavior:'smooth'});
}

function closeDeviceEditor(){
  devDraft=null; devEditingIdx=-1;
  document.getElementById('deviceEditor').style.display='none';
}

function readDevBase(){
  devDraft.name=document.getElementById('d_name').value.trim();
  devDraft.ip=document.getElementById('d_ip').value.trim();
  devDraft.enabled=document.getElementById('d_enabled').value==='1';
  const mode=document.getElementById('d_upmode').value;
  devDraft.upstream={
    mode:mode,
    api_base:document.getElementById('d_api_base').value.trim(),
    api_key:document.getElementById('d_api_key').value.trim(),
    api_model:document.getElementById('d_api_model').value.trim()
  };
}

function addDevRule(){
  devDraft.rules=devDraft.rules||[];
  devDraft.rules.push({name:'',enabled:true,match_type:'model',match_value:'',scope:'all',use_regex:false,
    block_start:'## 守住世界观',block_end:'## 角色属性',keep_marks:true,require_keywords:'',persona_text:''});
  renderDevRules();
}

function renderDevRules(){
  const box=document.getElementById('devRules');
  box.innerHTML='';
  (devDraft.rules||[]).forEach((r,k)=>{
    const d=document.createElement('div');
    d.style.cssText='border:1px solid #e3e5e8;border-radius:8px;padding:10px;margin:8px 0;background:#fff';
    d.innerHTML=`
      <div class="row">
        <div class="field"><label>规则名</label><input value="${r.name||''}" onchange="devRuleSet(${k},'name',this.value)"></div>
        <div class="field" style="max-width:150px"><label>匹配类型</label>
          <select onchange="devRuleSet(${k},'match_type',this.value)">
            <option value="model" ${r.match_type==='model'?'selected':''}>model</option>
            <option value="keyword" ${r.match_type==='keyword'?'selected':''}>关键词</option>
          </select>
        </div>
        <div class="field"><label>匹配值(model名/关键词)</label><input value="${r.match_value||''}" onchange="devRuleSet(${k},'match_value',this.value)"></div>
        <div class="field" style="max-width:120px"><label>启用</label>
          <select onchange="devRuleSet(${k},'enabled',this.value==='1')"><option value="1" ${r.enabled!==false?'selected':''}>启用</option><option value="0" ${r.enabled===false?'selected':''}>停用</option></select>
        </div>
      </div>
      <div class="row" style="margin-top:8px">
        <div class="field"><label>区间起始标记</label><input value="${r.block_start||''}" onchange="devRuleSet(${k},'block_start',this.value)"></div>
        <div class="field"><label>区间结束标记</label><input value="${r.block_end||''}" onchange="devRuleSet(${k},'block_end',this.value)"></div>
        <div class="field" style="max-width:170px"><label>替换方式</label>
          <select onchange="devRuleSet(${k},'keep_marks',this.value==='1')">
            <option value="1" ${r.keep_marks!==false?'selected':''}>保留标记换中间</option>
            <option value="0" ${r.keep_marks===false?'selected':''}>连标记整段替换</option>
          </select>
        </div>
      </div>
      <div class="row" style="margin-top:8px">
        <div class="field"><label>区间内必含关键词(逗号分隔,全中才替换,可空)</label><input value="${r.require_keywords||''}" onchange="devRuleSet(${k},'require_keywords',this.value)"></div>
      </div>
      <div style="margin-top:8px"><label>人设文本</label><textarea style="min-height:70px" onchange="devRuleSet(${k},'persona_text',this.value)">${r.persona_text||''}</textarea></div>
      <div class="row" style="margin-top:6px"><button class="danger" onclick="removeDevRule(${k})">删除该规则</button></div>`;
    box.appendChild(d);
  });
}

function devRuleSet(k,key,val){ devDraft.rules[k][key]=val; }
function removeDevRule(k){ devDraft.rules.splice(k,1); renderDevRules(); }

async function saveDevice(){
  readDevBase();
  if(!devDraft.ip){ alert('请填写设备 IP'); return; }
  if(devDraft.upstream.mode==='external' && (!devDraft.upstream.api_base||!devDraft.upstream.api_key)){
    alert('外援模式需填写接口地址和密钥'); return;
  }
  if(devEditingIdx>=0){ devices[devEditingIdx]=devDraft; } else { devices.push(devDraft); }
  await persistDevices();
  closeDeviceEditor();
}

async function removeDevice(i){ devices.splice(i,1); await persistDevices(); }
async function toggleDevice(i){ devices[i].enabled=devices[i].enabled===false?true:false; await persistDevices(); }

async function persistDevices(){
  await fetch('/api/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(devices)});
  await loadDevices();
  toast('设备已保存并即时生效');
}

// 复制QQ群号到剪贴板（clipboard API 优先，旧浏览器降级 execCommand）
async function copyGroup(num){
  try{
    await navigator.clipboard.writeText(num);
  }catch(e){
    const ta=document.createElement('textarea');
    ta.value=num; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  }
  toast('群号 '+num+' 已复制');
}

function toast(msg){
  const t=document.getElementById('toast');t.textContent=msg;t.style.display='block';
  setTimeout(()=>t.style.display='none',1800);
}

reloadConfig();
loadRules();
loadDevices();
</script>
</body>
</html>
"""


@app.route("/api/server", methods=["GET"])
def api_server():
    return jsonify({"host": RUN_HOST, "port": RUN_PORT,
                    "api_url": f"http://{RUN_HOST}:{RUN_PORT}/v1"})


@app.route("/")
def index():
    return Response(INDEX_HTML, content_type="text/html; charset=utf-8")



def _listen_host():
    import sys
    if len(sys.argv) > 1:
        return sys.argv[1]
    return read_config().get("listen_host") or LISTEN_HOST


def _listen_port():
    import sys
    try:
        if len(sys.argv) > 2:
            return int(sys.argv[2])
        return int(read_config().get("listen_port") or LISTEN_PORT)
    except (ValueError, TypeError):
        return LISTEN_PORT


if __name__ == "__main__":
    import webbrowser, threading
    
    apply_console_mode(read_config().get("console_debug", True))
    RUN_HOST = _listen_host()
    RUN_PORT = _listen_port()
    
    open_host = "127.0.0.1" if RUN_HOST in ("0.0.0.0", "") else RUN_HOST
    web_url = f"http://{open_host}:{RUN_PORT}/"
    print(f"规则编辑网页: {web_url}")
    print(f"游戏API地址: http://{RUN_HOST}:{RUN_PORT}/v1")
    
    threading.Timer(1.8, lambda: webbrowser.open(web_url)).start()
    app.run(host=RUN_HOST, port=RUN_PORT, threaded=True, debug=False)
