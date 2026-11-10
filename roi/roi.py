#!/usr/bin/env python3
"""Painel ROI dos Disparos Virtus — gera data/roi.json a partir de arquivos já baixados.

uso:
  roi.py build --csv vendas.csv --hp hp.json --custos custos.jsonl --tpl tpl.jsonl --cli cli.jsonl
               --origens origens.json --ate AAAA-MM-DD --out roi.json
  roi.py consultas --csv vendas.csv --hp hp.json --ate AAAA-MM-DD --out consultas.json
  roi.py hpfalta --csv vendas.csv --hp hp.json --out hp_falta.json

Entradas:
  vendas.csv   planilha "Backup vendas" do comercial (Google Drive, export CSV).
  hp.json      {"payload":{"data":[...]}} negócios do Clint com DealFields.field_cod_da_transferencia e Deal.contactId.
  custos/tpl/cli  arquivos .jsonl com uma linha por chamada {"input":{"query":...},"result":{...}} (páginas do Clint),
               ou .json com {"payload":{"data":[...]}} / lista de linhas.
  origens.json dataset "origens" publicado pelo Radar de Conversas (linhas tipo venda: dia, c, valor, vendedor, canal).
Saída sem nome, e-mail, telefone nem código da transação: venda leva dia, produto, valor, vendedor, origem
e a lista de disparos recebidos nos 15 dias antes da compra.
"""
import argparse, collections, csv, datetime as dt, hashlib, json, re, sys

INICIO = '2026-10-01'
JANELA_MAX = 15
PRECO = 0.54
OK = ('SENT', 'SUCCESS')


def D(s):
    return dt.date.fromisoformat(s[:10])


def dia_br(s):
    try:
        d, m, a = [int(x) for x in (s or '').strip().split('/')]
        return '%04d-%02d-%02d' % (a + 2000 if a < 100 else a, m, d)
    except Exception:
        return None


def brl(s):
    s = (s or '').strip().replace('R$', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0


def produto_planilha(r):
    p = (r.get('Produto') or '').upper()
    if 'IMERS' in p:
        return 'ISD'
    if 'PROTAGON' in p:
        return 'Protagon'
    n = (r.get('Nome do Produto') or '').upper()
    if 'IMERSÃO SPRINT' in n or 'IMERSAO SPRINT' in n:
        return 'ISD'
    if 'PROTAGON' in n:
        return 'Protagon'
    return None


# ---------- classificação dos templates (pelo nome) ----------
FUNIL_PROD = {'5f2a86db-a0cc-4aec-8e81-dec8f3606017': 'ISD', '0d22217f-063a-4f85-a276-0b4277d481ae': 'Protagon',
              '395e2051-56f6-4916-813c-5c35955e7f28': 'Protagon', 'd779c2f3-daaa-4bbb-b08b-f0343ba5cef1': 'Protagon'}


def produto_tpl(n):
    n = (n or '').lower()
    if 'coliseu' in n or n.startswith('col_'):
        return 'Coliseu'
    if '_5l' in n or n.endswith('5l'):
        return '5 Liberdades'
    if 'isd' in n:
        return 'ISD'
    if re.search(r'(^|_)(pro|protagon|met|jv|joinville|poa|goi|goiania|rp)(_|$|\d)', n) or 'protagon' in n:
        return 'Protagon'
    return 'Sem produto no nome'


TIPOS = ['Follow-up do vendedor', 'Abordagem de pré-checkout', 'Convite e lembrete de aula', 'Recuperação e resgate',
         'Campanha de venda em massa', 'Lista fria', 'Informativo', 'Outros']


def tipo_tpl(n):
    n = (n or '').lower()
    if 'frio' in n:
        return 'Lista fria'
    if any(k in n for k in ('webnario', 'web_convite', 'convite', 'encontro', 'zoom', 'sessao_estrategica', '_web_')):
        return 'Convite e lembrete de aula'
    if any(k in n for k in ('recupera', 'resgate', 'lost')):
        return 'Recuperação e resgate'
    if 'disparo' in n or any(k in n for k in ('ultimashoras', 'ultimosdias', 'retafinal', 'terror', 'corrido', 'motivo',
                                                         'flashopen', 'condicao_especial', 'cupom', 'merecimento', 'captada',
                                                         'naoaovivo', 'fora_24h', 'ultima_chamada', 'touch')):
        return 'Campanha de venda em massa'
    if 'abordagem' in n or 'precheckout' in n:
        return 'Abordagem de pré-checkout'
    if any(k in n for k in ('fup', 'follow', 'folllow', 'breakup', 'retomando', 'ultimato', 'confirmar_ligacao', 'mensagem1')):
        return 'Follow-up do vendedor'
    if any(k in n for k in ('informativa', 'utilidade')):
        return 'Informativo'
    return 'Outros'


# ---------- leitura das páginas do Clint ----------
def linhas_de(path):
    """Junta linhas de um .jsonl de chamadas (com paginação por offset) ou de um .json."""
    if path.endswith('.jsonl'):
        g = collections.defaultdict(dict)
        for ln in open(path, encoding='utf-8'):
            o = json.loads(ln)
            r, q = o['result'], o['input']['query']
            if not isinstance(r, dict) or 'payload' not in r or 'data' not in r['payload']:
                continue
            k = json.dumps({a: b for a, b in q.items() if a != 'offset'}, sort_keys=True)
            g[k][q.get('offset', 0)] = r['payload']['data']
        out = []
        for k, pags in g.items():
            offs = sorted(pags)
            for i, o in enumerate(offs):
                if o != i * 200:
                    sys.exit('ERRO: página faltando em %s: %s' % (path, offs))
            if len(pags[offs[-1]]) == 200:
                sys.exit('ERRO: última página cheia (falta paginar) em %s' % path)
            for o in offs:
                out += pags[o]
        return out
    d = json.load(open(path, encoding='utf-8'))
    if isinstance(d, dict):
        d = d.get('payload', d).get('data', d)
    return d


def ler_vendas(csv_path, ate):
    vs = []
    for i, r in enumerate(csv.DictReader(open(csv_path, encoding='utf-8-sig')), start=2):
        d = dia_br(r.get('Data de Venda'))
        hp = (r.get('Cod Transação') or '').strip()
        p = produto_planilha(r)
        if not d or d < INICIO or d > ate or not p:
            continue
        v = (r.get('Vendedor') or '').strip() or 'Sem vendedor'
        vs.append(dict(linha=i, cod=hp, dia=d, produto=p, valor=round(brl(r.get('Preço do Produto')), 2),
                       vendedor={'Vania': 'Vânia'}.get(v, v)))
    return vs


def contatos_por_hp(hp_path):
    by = collections.defaultdict(set)
    for r in linhas_de(hp_path):
        h = (r.get('DealFields.field_cod_da_transferencia') or '').strip()
        if h and r.get('Deal.contactId'):
            by[h].add(r['Deal.contactId'])
    return by


def _hash(c):
    return hashlib.sha1(('o' + c).encode()).hexdigest()[:10]


def cmd_hpfalta(a):
    vs = ler_vendas(a.csv, '2099-12-31')
    by = contatos_por_hp(a.hp)
    falta = sorted({v['cod'] for v in vs if v['cod'] and v['cod'] not in by})
    json.dump(falta, open(a.out, 'w'))
    print(len(falta), 'códigos HP sem contato no arquivo hp')


def cmd_consultas(a):
    vs = ler_vendas(a.csv, a.ate)
    by = contatos_por_hp(a.hp)
    cont = sorted({c for v in vs for c in by.get(v['cod'], ())})
    ini = (D(INICIO) - dt.timedelta(days=JANELA_MAX + 1)).isoformat()
    qs = [{"nome": "custos", "query": {"measures": ["Message.count"], "dimensions": ["Message.template_name", "Message.status"],
            "filters": [{"member": "Message.contentType", "operator": "equals", "values": ["Template"]},
                        {"member": "Message.type", "operator": "equals", "values": ["Atendente"]}],
            "timeDimensions": [{"dimension": "Message.createdAt", "dateRange": [INICIO, a.ate], "granularity": "day"}],
            "timezone": "America/Sao_Paulo", "order": {"Message.createdAt": "asc", "Message.template_name": "asc", "Message.status": "asc"},
            "limit": 200, "offset": 0}}]
    qs.append({"nome": "funil", "query": {"measures": ["Message.count"], "dimensions": ["Message.template_name", "Deal.originId"],
               "filters": [{"member": "Message.contentType", "operator": "equals", "values": ["Template"]},
                           {"member": "Message.type", "operator": "equals", "values": ["Atendente"]},
                           {"member": "Message.status", "operator": "equals", "values": ["SENT", "SUCCESS"]},
                           {"member": "Deal.originId", "operator": "equals", "values": list(FUNIL_PROD)}],
               "timeDimensions": [{"dimension": "Message.createdAt", "dateRange": [INICIO, a.ate]}],
               "timezone": "America/Sao_Paulo", "order": {"Message.template_name": "asc", "Deal.originId": "asc"}, "limit": 200, "offset": 0}})
    for i in range(0, len(cont), 60):
        lote = cont[i:i + 60]
        qs.append({"nome": "tpl_%d" % (i // 60), "query": {"measures": ["Message.count"], "dimensions": ["Contact.id", "Message.template_name", "Message.status"],
                   "filters": [{"member": "Message.contentType", "operator": "equals", "values": ["Template"]},
                               {"member": "Message.type", "operator": "equals", "values": ["Atendente"]},
                               {"member": "Contact.id", "operator": "equals", "values": lote}],
                   "timeDimensions": [{"dimension": "Message.createdAt", "dateRange": [ini, a.ate], "granularity": "day"}],
                   "timezone": "America/Sao_Paulo", "order": {"Contact.id": "asc", "Message.createdAt": "asc", "Message.template_name": "asc", "Message.status": "asc"},
                   "limit": 200, "offset": 0}})
        qs.append({"nome": "cli_%d" % (i // 60), "query": {"measures": ["Message.count"], "dimensions": ["Contact.id"],
                   "filters": [{"member": "Message.type", "operator": "equals", "values": ["Cliente"]},
                               {"member": "Contact.id", "operator": "equals", "values": lote}],
                   "timeDimensions": [{"dimension": "Message.createdAt", "dateRange": [ini, a.ate], "granularity": "day"}],
                   "timezone": "America/Sao_Paulo", "order": {"Contact.id": "asc", "Message.createdAt": "asc"}, "limit": 200, "offset": 0}})
    json.dump(qs, open(a.out, 'w'), ensure_ascii=False)
    print(len(vs), 'vendas,', len(cont), 'contatos,', len(qs), 'consultas')


def cmd_build(a):
    vs = ler_vendas(a.csv, a.ate)
    by = contatos_por_hp(a.hp)
    # custos por dia e template
    custos = collections.defaultdict(lambda: [0, 0])
    for r in linhas_de(a.custos):
        dia = (r.get('Message.createdAt.day') or r.get('Message.createdAt') or '')[:10]
        if not dia or dia < INICIO or dia > a.ate:
            continue
        k = (dia, r.get('Message.template_name') or '(sem nome)')
        custos[k][0 if r.get('Message.status') in OK else 1] += int(r['Message.count'])
    # disparos e respostas por contato
    T = collections.defaultdict(list)
    for p in a.tpl:
        for r in linhas_de(p):
            if r.get('Message.status') in OK:
                T[r['Contact.id']].append((r['Message.createdAt'][:10], r.get('Message.template_name') or '(sem nome)'))
    R = collections.defaultdict(set)
    for p in a.cli:
        for r in linhas_de(p):
            R[r['Contact.id']].add(r['Message.createdAt'][:10])
    # origem do comprador (Radar): chave dia + contato(hash) + valor
    org = {}
    for r in json.load(open(a.origens, encoding='utf-8')):
        if r.get('tipo') == 'venda':
            org.setdefault((r['dia'], r['c'], round(r.get('valor') or 0, 2)), r.get('canal') or '')
    tpls = {}
    vendas = []
    for v in vs:
        cs = sorted(by.get(v['cod'], ()))
        d = D(v['dia'])
        toques = set()
        for c in cs:
            resp = R.get(c, set())
            for t, n in T.get(c, ()):
                dd = (d - D(t)).days
                if 0 <= dd <= JANELA_MAX:
                    rr = any(D(t) <= D(x) <= D(t) + dt.timedelta(days=1) and D(x) <= d for x in resp)
                    toques.add((dd, n, rr))
                    tpls[n] = 1
        origem = ''
        for c in cs + [v['cod']]:
            origem = org.get((v['dia'], _hash(c), v['valor'])) or origem
            if origem:
                break
        vendas.append(dict(id='v%d' % v['linha'], dia=v['dia'], produto=v['produto'], valor=v['valor'],
                           vendedor=v['vendedor'], origem=origem or 'Sem origem no Radar', no_clint=bool(cs),
                           t=[[dd, n, 1 if rr else 0] for dd, n, rr in sorted(toques)]))
    nomes = sorted({n for _, n in custos} | set(tpls))
    # produto do template: pelo nome; sem produto no nome, dividido pela proporção de destinatários com negócio de lead
    # de ISD e de Protagon (consulta template × funil)
    fun = collections.defaultdict(collections.Counter)
    if a.funil:
        for r in linhas_de(a.funil):
            p = FUNIL_PROD.get(r.get('Deal.originId'))
            if p:
                fun[r.get('Message.template_name') or '(sem nome)'][p] += int(r['Message.count'])
    def prod_de(n):
        p = produto_tpl(n)
        if p != 'Sem produto no nome':
            return {p: 1}, 'nome'
        c = fun.get(n)
        if c and sum(c.values()):
            t = sum(c.values())
            return {k: round(v / t, 4) for k, v in c.items()}, 'funil'
        return {'Sem produto': 1}, 'sem'
    out = dict(gerado_em=dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).isoformat(timespec='minutes'),
               dados_ate=a.ate, inicio=INICIO, preco=PRECO, janela_max=JANELA_MAX, tipos=TIPOS,
               templates={n: [prod_de(n)[0], tipo_tpl(n), prod_de(n)[1]] for n in nomes},
               custos=[[d, n, s, e] for (d, n), (s, e) in sorted(custos.items())],
               vendas=vendas)
    json.dump(out, open(a.out, 'w'), ensure_ascii=False, separators=(',', ':'))
    env = sum(s for s, _ in custos.values()); err = sum(e for _, e in custos.values())
    com = [x for x in vendas if x['t']]
    semorig = sum(1 for x in vendas if x['origem'] == 'Sem origem no Radar')
    print(json.dumps(dict(dias=len({d for d, _ in custos}), enviados=env, erro=err, custo=round(env * PRECO, 2),
                          vendas=len(vendas), faturamento=round(sum(x['valor'] for x in vendas), 2),
                          com_disparo_15d=len(com), fat_com_disparo=round(sum(x['valor'] for x in com), 2),
                          sem_clint=sum(1 for x in vendas if not x['no_clint']), sem_origem_radar=semorig,
                          templates=len(nomes)), ensure_ascii=False))


def cmd_hpconsultas(a):
    vs = ler_vendas(a.csv, a.ate)
    cods = sorted({v['cod'] for v in vs if v['cod']})
    qs = []
    for i in range(0, len(cods), 100):
        qs.append({"nome": "hp_%d" % (i // 100), "query": {"measures": ["Deal.count"],
                   "dimensions": ["DealFields.field_cod_da_transferencia", "Deal.contactId", "Deal.id"],
                   "filters": [{"member": "DealFields.field_cod_da_transferencia", "operator": "equals", "values": cods[i:i + 100]}],
                   "order": {"Deal.id": "asc"}, "limit": 200, "offset": 0}})
    json.dump(qs, open(a.out, 'w'), ensure_ascii=False)
    print(len(cods), 'códigos HP,', len(qs), 'consultas')


def cmd_junta(a):
    """Junta as páginas cruas WORK/raw/<nome>_<offset>.json (resultado da execute_indicator_query, como veio)
    num .jsonl por grupo (prefixo do nome antes de '_' ou o nome inteiro): hp, custos, funil, tpl, cli."""
    import os
    qs = json.load(open(a.consultas, encoding='utf-8'))
    saida = collections.defaultdict(list)
    for q in qs:
        off = 0
        while True:
            p = os.path.join(a.raw, '%s_%d.json' % (q['nome'], off))
            if not os.path.exists(p):
                sys.exit('ERRO: falta a página %s' % p)
            t = open(p, encoding='utf-8').read()
            try:
                r = json.loads(t)
            except Exception:
                sys.exit('ERRO: página não é JSON: %s' % p)
            if isinstance(r, dict) and isinstance(r.get('result'), str):
                r = json.loads(r['result'])
            if isinstance(r, list) and r and isinstance(r[0], dict) and 'text' in r[0]:
                r = json.loads(r[0]['text'])
            if not isinstance(r, dict) or 'data' not in r.get('payload', {}):
                sys.exit('ERRO: página sem payload.data: %s' % p)
            qq = dict(q['query']); qq['offset'] = off
            g = q['nome'].split('_')[0]
            saida[g].append({'input': {'query': qq}, 'result': r})
            if len(r['payload']['data']) < 200:
                break
            off += 200
    for g, linhas in saida.items():
        with open(os.path.join(a.out, g + '.jsonl'), 'w', encoding='utf-8') as f:
            for o in linhas:
                f.write(json.dumps(o, ensure_ascii=False) + '\n')
        print(g, len(linhas), 'páginas,', sum(len(o['result']['payload']['data']) for o in linhas), 'linhas')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='c', required=True)
    p = sp.add_parser('build')
    for k in ('csv', 'hp', 'custos', 'origens', 'ate', 'out'):
        p.add_argument('--' + k, required=True)
    p.add_argument('--funil')
    p.add_argument('--tpl', nargs='+', required=True)
    p.add_argument('--cli', nargs='+', required=True)
    p = sp.add_parser('consultas')
    for k in ('csv', 'hp', 'ate', 'out'):
        p.add_argument('--' + k, required=True)
    p = sp.add_parser('hpfalta')
    for k in ('csv', 'hp', 'out'):
        p.add_argument('--' + k, required=True)
    p = sp.add_parser('hpconsultas')
    for k in ('csv', 'ate', 'out'):
        p.add_argument('--' + k, required=True)
    p = sp.add_parser('junta')
    for k in ('consultas', 'raw', 'out'):
        p.add_argument('--' + k, required=True)
    a = ap.parse_args()
    {'build': cmd_build, 'consultas': cmd_consultas, 'hpfalta': cmd_hpfalta, 'hpconsultas': cmd_hpconsultas, 'junta': cmd_junta}[a.c](a)
