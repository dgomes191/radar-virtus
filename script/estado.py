#!/usr/bin/env python3
"""Estado do Radar em arquivos (em vez de copiar o banco do painel).
  pack   --store DIR --out DIR        -> um arquivo estado_<colecao>.json por coleção {doc_id: documento}
  unpack --dir DIR --store DIR        -> recria DIR/store/<colecao>/<doc_id>.json
  bundle --cfg DIR --out F            -> pacote de código {nome_arquivo: texto}
  unbundle --file F --out DIR         -> grava os arquivos do pacote
Arquivo grande (> 12 MB) é dividido em partes estado_<colecao>__pN.json."""
import argparse, glob, json, os
LIM = 12_000_000
def pack(a):
    os.makedirs(a.out, exist_ok=True); res = {}
    for col in sorted(os.listdir(a.store)):
        p = os.path.join(a.store, col)
        if not os.path.isdir(p): continue
        docs = {}
        for f in sorted(glob.glob(os.path.join(p, '*.json'))):
            docs[os.path.basename(f)[:-5]] = json.load(open(f, encoding='utf-8'))
        parts, cur, size = [], {}, 0
        for k, v in docs.items():
            b = len(json.dumps(v, ensure_ascii=False).encode())
            if cur and size + b > LIM: parts.append(cur); cur, size = {}, 0
            cur[k] = v; size += b
        parts.append(cur)
        for i, part in enumerate(parts):
            fn = f'estado_{col}.json' if len(parts) == 1 else f'estado_{col}__p{i}.json'
            json.dump({'colecao': col, 'docs': part}, open(os.path.join(a.out, fn), 'w'), ensure_ascii=False, separators=(',', ':'))
            res[fn] = len(part)
    print(json.dumps(res, ensure_ascii=False))
def unpack(a):
    n = {}
    for f in sorted(glob.glob(os.path.join(a.dir, '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        if not isinstance(d, dict) or 'colecao' not in d: continue
        col = d['colecao']; os.makedirs(os.path.join(a.store, col), exist_ok=True)
        for k, v in d['docs'].items():
            json.dump(v, open(os.path.join(a.store, col, k + '.json'), 'w'), ensure_ascii=False); n[col] = n.get(col, 0) + 1
    print(json.dumps(n, ensure_ascii=False))
def bundle(a):
    b = {os.path.basename(f): open(f, encoding='utf-8').read() for f in sorted(glob.glob(os.path.join(a.cfg, '*'))) if os.path.isfile(f)}
    json.dump({'pacote': 'radar_codigo', 'arquivos': b}, open(a.out, 'w'), ensure_ascii=False); print(sorted(b))
def unbundle(a):
    d = json.load(open(a.file, encoding='utf-8')); os.makedirs(a.out, exist_ok=True)
    for k, v in d['arquivos'].items(): open(os.path.join(a.out, k), 'w', encoding='utf-8').write(v)
    print(sorted(d['arquivos']))
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest='c', required=True)
    p = sp.add_parser('pack'); p.add_argument('--store', required=True); p.add_argument('--out', required=True)
    p = sp.add_parser('unpack'); p.add_argument('--dir', required=True); p.add_argument('--store', required=True)
    p = sp.add_parser('bundle'); p.add_argument('--cfg', required=True); p.add_argument('--out', required=True)
    p = sp.add_parser('unbundle'); p.add_argument('--file', required=True); p.add_argument('--out', required=True)
    a = ap.parse_args(); {'pack': pack, 'unpack': unpack, 'bundle': bundle, 'unbundle': unbundle}[a.c](a)
