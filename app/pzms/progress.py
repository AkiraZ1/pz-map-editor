"""Progresso de tarefas longas (portado de saopaulo/scripts/progresso.py + painel_progresso.py).

API dos workers (thread ou subprocesso):
    mark(etapa, feito, total, msg)   -> MACRO (etapa atual)
    finish(etapa, msg)               -> etapa concluida
    micro(etapa, chave, msg, frac)   -> MICRO: o que ESTE worker faz agora (um registro por worker)
    log(linha)                       -> LOG da operacao
Tudo fica em <data>/progress/<op>/ (progress.json, micro/<worker>.json, op.log) com escrita atomica,
para subprocessos tambem reportarem. O painel (GET /api/progress) junta MACRO, sinais de vida
(CPU dos workers + ultimo arquivo gravado), MICRO e as ultimas linhas do LOG.
Nada aqui entra em chaves de cache incremental: so grava arquivos de status.
"""
import json
import os
import threading
import time

from . import gamedir

_lock = threading.Lock()
_cur = {"op": None}
_t0 = {}


def base(op=None):
    op = op or _cur["op"] or os.environ.get("PZMS_OP") or "geral"
    return os.path.join(gamedir.data_dir(), "progress", op)


def _wjson(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except OSError:
        pass


def begin(op, steps, outputs=(), title=""):
    """inicia uma operacao: etapas (MACRO) e pastas de saida (para 'ultimo arquivo gravado')."""
    with _lock:
        _cur["op"] = op
        _t0.clear()
        b = base(op)
        os.makedirs(os.path.join(b, "micro"), exist_ok=True)
        for f in os.listdir(os.path.join(b, "micro")):
            try:
                os.remove(os.path.join(b, "micro", f))
            except OSError:
                pass
        with open(os.path.join(b, "op.log"), "w", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + f"inicio: {title or op}\n")
        _wjson(os.path.join(b, "op.json"), {"op": op, "title": title or op, "steps": list(steps),
                                           "outputs": [str(o) for o in outputs], "t0": time.time(),
                                           "pid": os.getpid(), "done": False})
        _wjson(os.path.join(b, "progress.json"), None)
    os.environ["PZMS_OP"] = op


def end(op=None, error=None):
    p = os.path.join(base(op), "op.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    d.update(done=True, error=error, t1=time.time())
    _wjson(p, d)
    log("erro: " + error if error else "concluido", op)


def mark(etapa, feito, total, msg="", op=None):
    t = time.time()
    _t0.setdefault(etapa, t)
    _wjson(os.path.join(base(op), "progress.json"),
           {"etapa": etapa, "feito": feito, "total": total, "t0": _t0[etapa], "ts": t, "msg": msg})


def finish(etapa, msg="ok", op=None):
    mark(etapa, 1, 1, msg, op)


def micro(etapa, chave, msg, frac=None, op=None, worker=None):
    w = worker or f"{os.getpid()}-{threading.get_ident()}"
    _wjson(os.path.join(base(op), "micro", f"{w}.json"),
           {"etapa": etapa, "pid": os.getpid(), "worker": w, "chave": chave, "msg": msg, "frac": frac, "ts": time.time()})


def micro_done(op=None, worker=None):
    w = worker or f"{os.getpid()}-{threading.get_ident()}"
    try:
        os.remove(os.path.join(base(op), "micro", f"{w}.json"))
    except OSError:
        pass


def log(line, op=None):
    try:
        with open(os.path.join(base(op), "op.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + str(line).rstrip() + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- leitura (painel)
def _proc(pids):
    """{pid: (cpu%, MB)} via ps (Mac) ou tasklist/psutil ausente (Windows: so memoria)."""
    out = {}
    if not pids:
        return out
    try:
        import subprocess
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=3,
                               creationflags=0x08000000).stdout
            for l in r.splitlines():
                a = [x.strip('"') for x in l.split('","')]
                if len(a) >= 5 and a[1].isdigit() and int(a[1]) in pids:
                    out[int(a[1])] = (None, int("".join(c for c in a[4] if c.isdigit()) or 0) // 1024)
        else:
            r = subprocess.run(["ps", "-o", "pid=,pcpu=,rss=", "-p", ",".join(map(str, pids))],
                               capture_output=True, text=True, timeout=3).stdout
            for l in r.splitlines():
                a = l.split()
                if len(a) == 3:
                    out[int(a[0])] = (float(a[1]), int(a[2]) // 1024)
    except Exception:          # noqa: BLE001 - painel nunca derruba a operacao
        pass
    return out


_cpu_prev = {}


def _self_cpu():
    """CPU do proprio processo (threads) por delta de process_time (funciona em Mac e Windows)."""
    t, c = time.time(), time.process_time()
    pt, pc = _cpu_prev.get("s", (t, c))
    _cpu_prev["s"] = (t, c)
    return 100.0 * (c - pc) / (t - pt) if t > pt else 0.0


def _last_file(dirs, since):
    best = (0, "")
    for d in dirs:
        try:
            for root, _ds, fs in os.walk(d):
                for f in fs:
                    try:
                        m = os.stat(os.path.join(root, f)).st_mtime
                    except OSError:
                        continue
                    if m > best[0]:
                        best = (m, os.path.join(root, f))
        except OSError:
            pass
    return best if best[0] >= since - 1 else (0, "")


def _alive(pid):
    if pid == os.getpid():
        return True
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def tail(path, n=40):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 16384))
            return f.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return []


def snapshot(op=None, n=40):
    """estado do painel: macro (trilha, barra, eta), vida, micro e log."""
    b = base(op)
    try:
        with open(os.path.join(b, "op.json"), encoding="utf-8") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return None
    now = time.time()
    try:
        with open(os.path.join(b, "progress.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = None
    ms = []
    md = os.path.join(b, "micro")
    for fn in os.listdir(md) if os.path.isdir(md) else []:
        try:
            with open(os.path.join(md, fn), encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if _alive(m["pid"]):
            ms.append(m)
        else:
            try:
                os.remove(os.path.join(md, fn))
            except OSError:
                pass
    ms.sort(key=lambda m: str(m["chave"]))
    pids = {m["pid"] for m in ms} | {o["pid"]}
    pr = _proc(pids - {os.getpid()})
    own = _self_cpu()
    for m in ms:
        cpu, mb = pr.get(m["pid"], (None, None))
        if m["pid"] == os.getpid():
            cpu, mb = None, None
        m["cpu"], m["mb"], m["age"] = cpu, mb, now - m["ts"]
    cpu_total = own + sum(c for c, _ in pr.values() if c)
    lt, lf = _last_file(o.get("outputs", []), o["t0"])
    macro = None
    if d:
        parc = sum(m["frac"] or 0 for m in ms if m["etapa"] == d["etapa"] and d["feito"] < d["total"])
        fr = min(1.0, (d["feito"] + parc) / max(1, d["total"]))
        dt = (now if parc else d["ts"]) - d["t0"]
        eta = dt / fr - dt if 0 < fr < 1 and dt > 5 else None
        steps = o["steps"]
        i = steps.index(d["etapa"]) if d["etapa"] in steps else -1
        trail = [{"step": s, "state": "done" if k < i or (k == i and fr >= 1) or o.get("done") and not o.get("error")
                  else "cur" if k == i else "todo"} for k, s in enumerate(steps)]
        macro = {"step": d["etapa"], "done": d["feito"], "total": d["total"], "frac": fr, "elapsed": now - o["t0"],
                 "step_elapsed": now - d["t0"], "eta": eta, "since_mark": now - d["ts"], "msg": d.get("msg", ""),
                 "trail": trail}
    else:
        macro = {"trail": [{"step": s, "state": "todo"} for s in o["steps"]], "frac": 0, "elapsed": now - o["t0"]}
    if o.get("done"):
        live = {"state": "idle", "text": "concluido" if not o.get("error") else "erro"}
    elif cpu_total > 20 or (lt and now - lt < 120) or (d and now - d["ts"] < 30) or any(m["age"] < 30 for m in ms):
        live = {"state": "working", "text": f"trabalhando (cpu {cpu_total:.0f}%" +
                (f", ultimo arquivo ha {fmt(now - lt)})" if lt else ")")}
    elif not _alive(o["pid"]):
        live = {"state": "idle", "text": "nenhum processo rodando"}
    else:
        live = {"state": "stalled", "text": f"parado? cpu {cpu_total:.0f}%" +
                (f" e nada gravado ha {fmt(now - lt)}" if lt else " e nenhum arquivo gravado ainda")}
    return {"op": o["op"], "title": o.get("title"), "done": o.get("done", False), "error": o.get("error"),
            "macro": macro, "live": live, "micro": ms,
            "last_file": {"path": lf, "age": now - lt} if lf else None, "log": tail(os.path.join(b, "op.log"), n)}


def fmt(s):
    s = int(max(0, s))
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def current():
    return _cur["op"]
