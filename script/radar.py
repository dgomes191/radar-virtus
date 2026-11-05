import re
#!/usr/bin/env python3
"""Radar de Conversas Virtus — rotina diária.

Comandos:
  lotes    --origins F --q1 F --q2 F --q3 F --dia YYYY-MM-DD --out DIR
           monta os lotes de leitura do dia, as instruções do leitor e a linha da base inteira do dia
  merge    --reads DIR --dia YYYY-MM-DD --lotes DIR --out DIR
           transforma as leituras do dia em documentos novos do banco (radar_lotes)
  datasets --store DIR --out DIR
           gera conversas.json, objecoes.json, frases.json, base.json, maos.json e origens.json a partir do banco
  origensdia --leads F[,F] --vendas F --hist F --dia YYYY-MM-DD --out F
           leads que entraram no dia por canal (Forms, Inlead, webinário…) e vendas do comercial do dia com o canal do lead
Arquivos de consulta (q1, q2, q3, origins) = resultado cru das ferramentas do Clint, como foram salvos.
"""
import argparse, collections, datetime as dt, glob, hashlib, json, os, re

# ---------- utilidades ----------
def rows_of(path):
    txt = open(path, encoding="utf-8").read()
    d = json.loads(txt)
    def f(o):
        if isinstance(o, dict):
            if isinstance(o.get("data"), list): return o["data"]
            for v in o.values():
                r = f(v)
                if r is not None: return r
        if isinstance(o, list):
            if o and isinstance(o[0], dict) and any("." in k for k in o[0]): return o
            for v in o:
                r = f(v)
                if r is not None: return r
        return None
    return f(d) or []

def origins_of(path):
    d = json.loads(open(path, encoding="utf-8").read())
    def f(o):
        if isinstance(o, list) and o and isinstance(o[0], dict) and "group" in o[0]: return o
        if isinstance(o, dict):
            for v in o.values():
                r = f(v)
                if r is not None: return r
        return None
    return f(d) or []

def rid(contact, produto):
    return ("isd-" if produto == "ISD" else "pro-") + hashlib.sha1((contact + str(produto)).encode()).hexdigest()[:8]

def semana(data):
    d = dt.date.fromisoformat(data[:10])
    ini = d - dt.timedelta(days=d.weekday())
    fim = ini + dt.timedelta(days=6)
    mes = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    rot = f"{ini.day:02d}/{mes[ini.month-1]} a {fim.day:02d}/{mes[fim.month-1]}"
    return ini.isoformat(), rot

NAO_COMPRA_PAL = ("doação", "doacao", "reembolso", "chargeback", "evento protagon", "checkin", "check-in")

def produto_da_origem(o):
    g = (o.get("group") or {}).get("name", "") or ""
    n = o.get("name", "") or ""
    G = g.upper()
    if "ISD" in G: p = "ISD"
    elif "PROTAGON" in G: p = "Protagon"
    else: p = None
    nao = any(k in (g + " " + n).lower() for k in NAO_COMPRA_PAL)
    return p, nao

# ---------- comando lotes ----------
def cmd_lotes(a):
    dia = a.dia
    ini15 = (dt.date.fromisoformat(dia) - dt.timedelta(days=14)).isoformat()
    om = {}
    for o in origins_of(a.origins):
        om[o["id"]] = produto_da_origem(o)
    # q1: mensagens do lead (texto) nos 15 dias, por contato e chat
    msgs15 = collections.Counter(); chats = collections.defaultdict(set)
    for r in rows_of(a.q1):
        c = r.get("Contact.id"); n = int(r.get("Message.count") or 0)
        msgs15[c] += n
        if r.get("Chat.id"): chats[c].add(r["Chat.id"])
    # q2: mensagens do dia por hora (lead e time)
    cli = collections.defaultdict(list); hum = collections.defaultdict(list)
    for r in rows_of(a.q2):
        c = r.get("Contact.id")
        h = (r.get("Message.createdAt.hour") or r.get("Message.createdAt") or "")[:13]
        if r.get("Message.type") == "Cliente": cli[c].append(h)
        elif r.get("Message.source") in ("Chat", "Fora da Clint"): hum[c].append(h)
    # q3: negócios dos contatos que escreveram no dia
    prods = collections.defaultdict(set); comprou = collections.defaultdict(set); cliente = collections.defaultdict(set)
    sem_map = set()
    for r in rows_of(a.q3):
        c = r.get("Contact.id"); oid = r.get("Origin.id") or ""
        if oid not in om: sem_map.add(oid); continue
        p, nao = om[oid]
        if not p: continue
        prods[c].add(p)
        if r.get("Deal.status") == "WON" and not nao:
            w = (r.get("Deal.wonAt") or r.get("Deal.createdAt") or "")[:10]
            if ini15 <= w <= dia: comprou[c].add(p)
            elif w and w < ini15: cliente[c].add(p)
    os.makedirs(a.out, exist_ok=True)
    # base inteira do dia
    base = collections.Counter()
    sel = []
    for c in cli:
        for p in prods.get(c, ()):
            grupo = "Compraram" if p in comprou[c] else ("cliente" if p in cliente[c] else "Não compraram")
            if grupo == "cliente": continue
            faixa = "3 ou mais mensagens" if msgs15[c] >= 3 else "1 ou 2 mensagens"
            th = bool(hum.get(c))
            sem = (not hum.get(c)) or max(hum[c]) < max(cli[c])
            for pp in (p, "Todos"):
                k = (pp, grupo, faixa)
                base[k + ("escreveram",)] += 1; base[k + ("com_vendedor",)] += th; base[k + ("terminou_sem_vendedor",)] += sem
        if msgs15[c] >= 3:
            ps = [p for p in prods.get(c, ()) if not (p in cliente[c] and p not in comprou[c])]
            if ps:
                grupo = "comprou" if any(p in comprou[c] for p in ps) else "nao_comprou"
                ps = [p for p in ps if (p in comprou[c]) == (grupo == "comprou")] or ps
                sel.append({"contact": c, "produto": ps, "grupo": grupo, "chats": sorted(chats[c])})
    linhas = []
    keys = sorted({k[:3] for k in base})
    for k in keys:
        linhas.append({"id": f"{dia}|{k[0]}|{k[1]}|{k[2]}", "dia": dia, "produto": k[0], "aba": k[1], "faixa": k[2],
                       "escreveram": base[k + ("escreveram",)], "com_vendedor": base[k + ("com_vendedor",)],
                       "terminou_sem_vendedor": base[k + ("terminou_sem_vendedor",)]})
    json.dump({"dia": dia, "linhas": linhas}, open(os.path.join(a.out, "doc_dia.json"), "w"), ensure_ascii=False)
    for i in range(0, len(sel), 25):
        json.dump(sel[i:i+25], open(os.path.join(a.out, f"lote_{i//25:03d}.json"), "w"), ensure_ascii=False)
    if a.template:
        t = open(a.template, encoding="utf-8").read()
        t = t.replace("{INICIO}", ini15).replace("{FIM}", dia).replace("{WORKDIR}", os.path.abspath(a.out))
        open(os.path.join(a.out, "INSTRUCOES.md"), "w", encoding="utf-8").write(t)
    print(json.dumps({"dia": dia, "janela_3mais": [ini15, dia], "contatos_escreveram": len(cli), "a_ler": len(sel),
                      "lotes": (len(sel) + 24)//25, "origens_sem_mapa": len(sem_map)}, ensure_ascii=False))

# ---------- normalização (mesmas regras da leitura de 8 a 22/out) ----------
VEND = {"Suellen Moreira": "Suellen", "Gabi": "Gabriela", "Gabriela Ferreira": "Gabriela", "Priscila Tegani": "Pry",
        "Priteganif": "Pry", "Pri": "Pry", "Priscila": "Pry", "Jaldo Junior": "Jaldo", "Emanoelle Einecke": "Emanoelle", "Furlan": "Gabriel Furlan",
        "": "Nenhum", None: "Nenhum"}
def norm_vend(r):
    v = r.get("vendedor"); v = VEND.get(v, v)
    if v == "Nenhum" and r.get("teve_humano"): v = "Não identificado"
    return v
def norm_caminho(r):
    c = r.get("caminho") or "Outro"
    if r["grupo"] == "comprou" or c == "Comprador tratado como lead": return c
    if r.get("lead_sem_resposta") and r.get("ultima_fala") == "Lead": return "Ficou sem resposta do time"
    if c in ("Sem interesse", "Esperava evento gratuito", "Data ou agenda", "Esperando outra pessoa"): return c
    prop = r.get("recebeu_proposta")
    if prop is None: prop = bool(r.get("preco_final") or r.get("ancora"))
    if not prop: return "Nunca recebeu proposta"
    if c in ("Ainda negociando", "Sumiu depois do preço", "Nunca recebeu proposta", "Outro", "Ficou sem resposta do time"):
        return "Ainda negociando" if r.get("_recente") else "Sumiu depois do preço"
    return c
EM_ABERTO = {"Ainda negociando", "Esperando outra pessoa", "Ficou sem resposta do time", "Nunca recebeu proposta", "Sumiu depois do preço"}
def s(v): return (v or "").strip() if isinstance(v, str) else ("" if v is None else v)

def to_store(r, dia_leitura):
    """leitura crua -> documento do banco (sem dado pessoal)"""
    if r.get("produto") not in ("ISD", "Protagon") or not r.get("valida"): return None
    data = s(r.get("data")) or dia_leitura
    r["_recente"] = (dt.date.fromisoformat(dia_leitura) - dt.date.fromisoformat(data[:10])).days <= 2
    r["caminho"] = norm_caminho(r)
    des = "Comprou" if r["grupo"] == "comprou" else ("Em aberto" if r["caminho"] in EM_ABERTO else "Perdido")
    i = rid(r["contact"], r["produto"])
    return {"id": i, "lido_em": dia_leitura, "produto": r["produto"], "praca": s(r.get("praca")) or "Não citada", "data": data[:10],
            "vendedor": norm_vend(r), "desfecho": des, "aba": "Compraram" if r["grupo"] == "comprou" else "Não compraram",
            "perfil": s(r.get("perfil")), "desejo": s(r.get("desejo")), "objecao_principal": s(r.get("objecao_principal")) or "Nenhuma",
            "pediu_dupla": "Sim" if r.get("pediu_dupla") else "Não", "sem_resposta": "Sim" if r.get("lead_sem_resposta") else "Não",
            "caminho": r["caminho"], "o_que_fechou": s(r.get("o_que_fechou")), "motivo_perda": s(r.get("motivo_perda")),
            "horas_ate_humano": r.get("horas_ate_humano"), "ancora": r.get("ancora"), "preco_final": r.get("preco_final"),
            "ultima_fala": s(r.get("ultima_fala")), "teve_humano": "Sim" if r.get("teve_humano") else "Não",
            "pos_venda_sem_resposta": "Sim" if r.get("pos_venda_sem_resposta") else "Não",
            "comprador_recebeu_venda": "Sim" if r.get("comprador_recebeu_venda") else "Não", "obs": s(r.get("obs")),
            "objecoes": [{"categoria": o.get("categoria"), "trecho": s(o.get("trecho"))} for o in (r.get("objecoes") or []) if isinstance(o, dict) and o.get("categoria")],
            "frases": [{"tipo": s(f.get("tipo")), "frase": s(f.get("frase")), "quem": s(f.get("quem")), "uso": s(f.get("uso"))} for f in (r.get("frases") or []) if isinstance(f, dict) and f.get("frase")]}

def write_chunks(docs, prefix, out):
    os.makedirs(out, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
    n = 0; cur = []; size = 0; files = []
    def flush():
        nonlocal n, cur, size
        if not cur: return
        fn = os.path.join(out, f"{prefix}_{stamp}_{n:02d}.json")
        json.dump({"linhas": cur}, open(fn, "w"), ensure_ascii=False); files.append(fn)
        n += 1; cur = []; size = 0
    for d in docs:
        b = len(json.dumps(d, ensure_ascii=False).encode())
        if size + b > 180_000: flush()
        cur.append(d); size += b
    flush()
    return files

# ---------- comando merge ----------
def cmd_merge(a):
    lot = {}
    for f in glob.glob(os.path.join(a.lotes, "lote_*.json")):
        for x in json.load(open(f)):
            if not x.get("amostra_1_2"): lot[x["contact"]] = x
    rows = {}
    for f in sorted(glob.glob(os.path.join(a.reads, "*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if not ln: continue
            try: r = json.loads(ln)
            except Exception: continue
            if r.get("contact") not in lot: continue
            r["grupo"] = lot[r["contact"]]["grupo"]
            rows[(r["contact"], r.get("produto"))] = r
    docs = [d for d in (to_store(r, a.dia) for r in rows.values()) if d]
    files = write_chunks(docs, f"lote_{a.dia.replace('-', '')}", a.out)
    print(json.dumps({"leituras": len(rows), "validas": len(docs), "documentos": [os.path.basename(f)[:-5] for f in files]}, ensure_ascii=False))

# ---------- comando datasets ----------
def load_docs(path):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        try: d = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        out.append((os.path.basename(f)[:-5], d))
    # documentos grandes divididos em partes (limite de 256 KB por documento): mesmo "grupo" vira um documento só, com o nome do grupo
    grupos = {}
    res = []
    for name, d in out:
        g = d.get("grupo") if isinstance(d, dict) else None
        if not g: res.append((name, d)); continue
        if g not in grupos:
            base = dict(d); grupos[g] = base; res.append((g, base))
        else:
            base = grupos[g]
            for k in ("linhas", "leads", "vendas"):
                if isinstance(d.get(k), list): base[k] = list(base.get(k) or []) + d[k]
    return res

# ---------- objeção específica (o que é "preço", "pagamento"…) a partir do trecho dito pelo lead ----------
import unicodedata
def _N(s): return unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
# (categoria, regex no trecho) -> subobjeção ; ordem importa; última regra da categoria é o padrão
OBJ_REGRAS = {
 'Preço': [
  (r'ribeir|amigo conseguiu|400|paguei|697|link.*valor|aparece por|mais caro|mesmo preco de 2|ano passado|sao paulo nao paguei|baixou', 'Viu preço menor em outra praça, link ou com outra pessoa'),
  (r'desconto|melhor(ar|a)|oferta melhor|descontinho|cupom|melhor condicao|melhor valor|melhor peco|faz 500|proposta de 600|situacao boa|a vista|convite gratuito|cortesia|mais barato|diminuir', 'Pede desconto ou condição melhor para fechar'),
  (r'dois|2|casa(l|is)|esposo|ingresso dele|para os 2', 'Valor pesa porque vai em dupla'),
  (r'^(depende|quais|qual|so preciso saber|e eu quero saber|quero saber|nao, somente|a de)|valores|quanto', 'Quer saber o preço antes de qualquer conversa'),
  (r'dobro|tres dias|3 dias|por dia|vale a pena|95%|investir nessas ferramentas|capital inicial|executivo|vip|basica|diamond', 'Não vê valor que justifique o preço / compara categorias'),
  (r'.', 'Não tem o dinheiro agora / fora do orçamento'),
 ],
 'Pagamento ou parcelamento': [
  (r'limite|cartao fisico|nao passou|nao esta passando|credito disponivel|cartao fechar|virar|vira |virada', 'Sem limite no cartão ou esperando o cartão virar'),
  (r'boleto|recorren|nao tenho cartao|nao faco o uso de cartao|especie|nao tem cartao', 'Quer boleto parcelado ou cobrança recorrente (sem cartão)'),
  (r'juros|12x|quantas vezes|parcela|parcelado|1000 mensal|1.000 mensal|dividir|financiar', 'Quer parcelar mais ou sem juros'),
  (r'pix|parte|entrada|link com esse valor', 'Quer dividir o pagamento (Pix + cartão, entrada)'),
  (r'.', 'Dinheiro entra depois: pede para segurar a condição até a data'),
 ],
 'Data ou agenda': [
  (r'so (no )?sabado|so dia 15|somente no sabado|nao conseguir estar todas|chegar as 14|sexta|horario|madrugada|perderia', 'Só consegue ir em parte do evento ou em outro horário'),
  (r'proxim|2027|ano que vem|longe ainda|abril|dezembro|quando tera|outra turma|outra oportunidade', 'Data não serve: pede a próxima turma'),
  (r'.', 'Já tem compromisso na data do evento'),
 ],
 'Local ou deslocamento': [
  (r'online|on-line|virtual|presencial', 'Prefere online ou gravado / não pode ir presencial'),
  (r'perto da minha|vai ter por aqui|nao vai ter|regiao|nordeste|previsao|data marcada|tera encontro|quando vai ter|mais proximo|^ola , \[cidade\]|^sao paulo$|so pode ser nessas', 'Quer edição na cidade/região dele'),
  (r'.', 'Mora longe: custo de viagem, hotel e deslocamento'),
 ],
 'Não entendeu o que é': [
  (r'ideia de produto|produto digital|area de atuacao|ideia solida|nao tenho nenhuma ideia|ja tem negocio|so pra quem', 'Acha que não tem perfil ou ideia de produto para aproveitar'),
  (r'online|video|presencial|ingresso|bonus|inclus|ia para trafego|real entrega|temas|muda muito|so sobre digital|metodo|mentoria|gratuito deste', 'Dúvida sobre o formato e o que está incluso'),
  (r'.', 'Não sabe o que é o evento nem como funciona'),
 ],
 'Decide com outra pessoa': [
  (r'alguem|amig|mais gnt|eles|mais alguem|ir comigo', 'Procurando alguém para ir junto antes de decidir'),
  (r'.', 'Precisa decidir com marido/esposa/sócio'),
 ],
 'Condição para dupla': [
  (r'ganhei|ganhou', 'Ganhou ingresso e quer levar acompanhante'),
  (r'nao tenho quem levar|desistiu|dividir', 'Sem dupla para ir'),
  (r'.', 'Quer preço ou condição para casal/dupla'),
 ],
 'Momento ou prioridade': [
  (r'eleic|politic|agro|cliente|empresa|emprego|renda|financ|orcamento|dificuldade', 'Momento financeiro ruim (empresa, clientes, eleição)'),
  (r'.', 'Agora não é prioridade / deixa para depois'),
 ],
 'Tempo ou rotina': [
  (r'filh|bebe|baba', 'Filhos: com quem deixar'),
  (r'.', 'Sem tempo: trabalho e rotina corrida'),
 ],
 'Desconfiança': [
  (r'golpe|verdade|oficial|perfil|equipe|ganhei|ingresso|confirmar|perigoso|link', 'Acha que pode ser golpe (ingresso grátis, número, link)'),
  (r'baixou|400|mais barato', 'Desconfia porque o preço caiu para outros'),
  (r'.', 'Medo de não ter resultado (ROI, empurrar outro curso)'),
 ],
 'Problema no checkout': [
  (r'acompanhante|parentesco|nome de quem|para ele|ficha', 'Não consegue cadastrar o acompanhante no checkout'),
  (r'valor|subiu|acima', 'Link com valor diferente do combinado'),
  (r'.', 'Erro no pagamento ou link expirado'),
 ],
 'Esperava gratuito': [(r'.', 'Achava que era gratuito')],
 'Outro': [
  (r'interesse|desisti|deixar passar|nao vou conseguir', 'Sem interesse / desistiu'),
  (r'online|gravado|cansativ|curso on', 'Prefere online ou gravado / não pode ir presencial'),
  (r'resposta|retornaram|dificil falar|demorou|suporte|nao recebi|msgs|mensagens|msg|link para entrar|ja comprei|consta|acessar', 'Atendimento demorado ou confuso (muitas mensagens, sem retorno)'),
  (r'.', 'Outros'),
 ],
}
def obj_sub(cat, trecho):
    t=_N(trecho)
    for rx,lab in OBJ_REGRAS.get(cat,[(r'.','Outros')]):
        if re.search(rx,t): return lab
    return 'Outros'


def cmd_datasets(a):
    latest = {}
    for name, d in sorted(load_docs(os.path.join(a.store, "radar_lotes")), key=lambda x: x[0]):
        for r in d.get("linhas", []):
            k = r["id"]
            if k not in latest or (r.get("lido_em", ""), name) >= (latest[k].get("lido_em", ""), latest[k].get("_doc", "")):
                r["_doc"] = name; latest[k] = r
    desde = getattr(a, "desde", "") or ""
    pessoas = {}
    for name, d in sorted(load_docs(os.path.join(a.store, "radar_contatos")), key=lambda x: x[0]):
        for l in d.get("linhas", []):
            if l.get("contact"): pessoas[l["contact"]] = l
    por_rid = {}
    for c, l in pessoas.items():
        for p in ("ISD", "Protagon"): por_rid[rid(c, p)] = l
    def quem(l):
        if not l: return {"lead": "", "email": ""}
        return {"lead": (l.get("nome") or "").strip().split(" ")[0].title(), "email": (l.get("email") or "").strip().lower()}
    audc = {}
    for name, d in sorted(load_docs(os.path.join(a.store, "radar_auditoria")), key=lambda x: x[0]):
        for l in d.get("linhas", []):
            if l.get("id"): audc[l["id"]] = l
    conv, obj, fra = [], [], []
    for r in latest.values():
        if desde and r["data"] < desde: continue
        sem, rot = semana(r["data"])
        base = {k: v for k, v in r.items() if k not in ("objecoes", "frases", "_doc", "lido_em")}
        base["semana"] = rot; base["semana_ini"] = sem
        _q = por_rid.get(r["id"])
        if _q or not (base.get("email") or base.get("lead")): base.update(quem(_q))  # base reconstruída: mantém lead/e-mail já gravados
        v = audc.get(r["id"])
        if v:
            base["revisao"] = {"confirmado": "Confirmado na 2ª leitura", "corrigir": "Corrigido na 2ª leitura", "duvida": "Em dúvida: conferir no Clint"}.get(v.get("veredito"), "")
            if v.get("veredito") == "corrigir" and v.get("caminho_certo"): base["caminho"] = v["caminho_certo"]
            if v.get("responsavel"): base["responsavel"] = nome_vend(v["responsavel"])
        conv.append(base)
        for j, o in enumerate(r.get("objecoes", [])):
            obj.append({"id": f"{r['id']}-o{j}", "conversa": r["id"], "produto": r["produto"], "data": r["data"], "semana": rot, "semana_ini": sem,
                        "categoria": o["categoria"], "sub": obj_sub(o["categoria"], o.get("trecho", "")), "trecho": o.get("trecho", ""), "desfecho": r["desfecho"], "aba": r["aba"]})
        for j, f_ in enumerate(r.get("frases", [])):
            fra.append({"id": f"{r['id']}-f{j}", "produto": r["produto"], "data": r["data"], "semana": rot, "semana_ini": sem, "tipo": f_.get("tipo", ""),
                        "frase": f_.get("frase", ""), "quem": f_.get("quem", ""), "uso": f_.get("uso", ""), "aba": r["aba"]})
    dias = {}
    for name, d in sorted(load_docs(os.path.join(a.store, "radar_dias")), key=lambda x: x[0]):
        if d.get("dia"): dias[d["dia"]] = d.get("linhas", [])
    base = []
    for dia, ls in sorted(dias.items()):
        if desde and dia < desde: continue
        sem, rot = semana(dia)
        for l in ls:
            l = dict(l); l["semana"] = rot; l["semana_ini"] = sem; base.append(l)
    maos = {}
    for name, d in sorted(load_docs(os.path.join(a.store, "radar_maos")), key=lambda x: x[0]):
        if d.get("dia") and d.get("metodo") == "mensagem": maos[d["dia"]] = d.get("linhas", [])
    mrows = []
    for dia, ls in sorted(maos.items()):
        sem, rot = semana(dia)
        for l in ls:
            p = pessoas.get(l.get("contato"))
            l = {k: v for k, v in l.items() if k != "contato"}; l["semana"] = rot; l["semana_ini"] = sem
            if p or not (l.get("email") or l.get("lead")): l.update(quem(p))  # base reconstruída: mantém lead/e-mail já gravados
            mrows.append(l)
    os.makedirs(a.out, exist_ok=True)
    json.dump(mrows, open(os.path.join(a.out, "maos.json"), "w"), ensure_ascii=False)
    orows = origens_rows(a.store, "2026-10-01")  # origens começam em 1º/out (pedido do Diego)
    json.dump(orows, open(os.path.join(a.out, "origens.json"), "w"), ensure_ascii=False)
    json.dump(levantadas_rows(a.store), open(os.path.join(a.out, "levantadas.json"), "w"), ensure_ascii=False)
    for nm, v in (("conversas", conv), ("objecoes", obj), ("frases", fra), ("base", base)):
        json.dump(v, open(os.path.join(a.out, nm + ".json"), "w"), ensure_ascii=False)
    print(json.dumps({"conversas": len(conv), "objecoes": len(obj), "frases": len(fra), "base_linhas": len(base),
                      "semanas": sorted({x["semana"] for x in conv}), "dias_base": sorted(dias), "origens_linhas": len(orows)}, ensure_ascii=False))


# ---------- comando maos (levantadas de mão) ----------
ISD_PRE = {"5f2a86db-a0cc-4aec-8e81-dec8f3606017", "319646dc-de82-4a00-a5e5-f3ed9f697e90", "dd675068-35ec-423f-93aa-3a93dcd08efc"}
def nome_vend(n):
    if not n: return None
    n = " ".join(n.split())
    low = n.lower()
    if low.startswith("priscila") or low.startswith("pry"): return "Pry"
    if low.startswith("gabriel furlan") or low == "furlan": return "Gabriel Furlan"
    first = n.split()[0].capitalize()
    return {"Suellen": "Suellen", "Vânia": "Vânia", "Vania": "Vânia"}.get(first, first)

def util_min(t0, t1):
    """minutos entre t0 e t1 contando só seg-sáb 08:00-20:00"""
    if t1 <= t0: return 0
    tot = 0; d = t0
    while d < t1:
        day = d.date()
        if day.weekday() < 6:
            ini = dt.datetime.combine(day, dt.time(8)); fim = dt.datetime.combine(day, dt.time(20))
            a = max(d, ini); b = min(t1, fim)
            if b > a: tot += (b - a).total_seconds() / 60
        d = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0))
    return tot

def no_horario(t): return t.weekday() < 6 and 8 <= t.hour < 20

def faixa(m):
    if m <= 5: return "Até 5 min"
    if m <= 15: return "5 a 15 min"
    if m <= 60: return "15 a 60 min"
    if m <= 240: return "1 a 4 h"
    return "Mais de 4 h"

def cmd_maos(a):
    P = lambda s_: dt.datetime.fromisoformat(s_[:19])
    corte = P(a.corte)
    hum = collections.defaultdict(list)
    for f in a.q6.split(","):
        for r in rows_of(f):
            t = r.get("Message.createdAt.minute") or r.get("Message.createdAt")
            if t and r.get("Contact.id"): hum[r["Contact.id"]].append((P(t), nome_vend(r.get("User.name"))))
    for v in hum.values(): v.sort()
    lead = collections.defaultdict(list)
    for f in a.q7.split(","):
        for r in rows_of(f):
            t = r.get("Message.createdAt.minute") or r.get("Message.createdAt")
            if t and r.get("Contact.id"): lead[r["Contact.id"]].append(P(t))
    ia = collections.defaultdict(list)
    for f in (a.ia.split(",") if a.ia else []):
        for r in rows_of(f):
            t = r.get("Message.createdAt.minute") or r.get("Message.createdAt")
            if t and r.get("Contact.id"): ia[r["Contact.id"]].append(P(t))
    V = carregar_verif(a.verif) if a.verif else {}
    first = {}
    for r in rows_of(a.q4):
        c = r.get("Contact.id"); t = r.get("TrackStage.date")
        if not c or not t: continue
        prod = "ISD" if r.get("TrackStage.originId") in ISD_PRE else "Protagon"
        tm = P(t)
        # só vale se o lead mandou mensagem (clique de botão ou texto) até 10 min antes da entrada em Conexão
        if not any(tm - dt.timedelta(minutes=10) <= x <= tm + dt.timedelta(minutes=1) for x in lead.get(c, [])): continue
        k = (c, t[:10], prod)
        if k not in first or t < first[k]["t"]: first[k] = {"t": t, "mover": nome_vend(r.get("User.name"))}
    dias = collections.defaultdict(list)
    for (c, dia, prod), v in first.items():
        if a.dias and dia not in a.dias.split(","): continue
        tm = P(v["t"]); hs = hum.get(c, [])
        antes = [h for h in hs if tm - dt.timedelta(minutes=60) <= h[0] < tm]
        depois = [h for h in hs if h[0] >= tm]
        if antes:
            sit, esp, vend = "Já em conversa", 0, antes[-1][1]
        elif depois:
            esp = round(util_min(tm, depois[0][0])); sit = faixa(esp); vend = depois[0][1]
        else:
            esp = None; vend = v["mover"] or "Sem dono"
            sit = "Sem resposta" if util_min(tm, corte) > 15 else "Aguardando"
        mid = "m-" + hashlib.sha1((c + prod + dia).encode()).hexdigest()[:10]
        if sit in ("Sem resposta", "Aguardando") and any(x >= tm for x in ia.get(c, [])): sit = "Só a IA respondeu"
        vf = V.get(mid, {})
        if vf.get("tipo") in ("encerrar", "auto_resposta"): sit = "Não era mão levantada"
        elif vf.get("ia") and sit in ("Sem resposta", "Aguardando"): sit = "Só a IA respondeu"
        linha = {"id": mid, "dia": dia, "hora": v["t"][11:16],
            "produto": prod, "vendedor": vend or "Sem dono", "situacao": sit, "espera_min": esp,
            "respondeu": "Não" if sit in ("Sem resposta", "Aguardando") else ("IA" if sit == "Só a IA respondeu" else ("—" if sit == "Não era mão levantada" else "Sim")),
            "fora_horario": "Não" if no_horario(tm) else "Sim", "conferido": "Sim" if vf else "Não",
            "conversa": rid(c, prod), "contato": c}
        if vf.get("msg"): linha["msg"] = vf["msg"][:80]
        dias[dia].append(linha)
    os.makedirs(a.out, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
    res = {}
    for dia, ls in sorted(dias.items()):
        fn = os.path.join(a.out, f"maos_{dia.replace('-', '')}_{stamp}.json")
        json.dump({"dia": dia, "linhas": ls}, open(fn, "w"), ensure_ascii=False)
        res[dia] = collections.Counter(l["situacao"] for l in ls)
    print(json.dumps({d: dict(c) for d, c in res.items()}, ensure_ascii=False))

def carregar_verif(caminho):
    V = {}
    arqs = sorted(glob.glob(os.path.join(caminho, "**", "*.json*"), recursive=True)) if os.path.isdir(caminho) else [caminho]
    for f in arqs:
        try:
            if f.endswith(".jsonl"): ls = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
            else: ls = json.load(open(f, encoding="utf-8")).get("linhas", [])
        except Exception: continue
        for l in ls:
            if l.get("id"): V[l["id"]] = l
    return V

# ---------- comando conferir: casos que precisam ter a conversa aberta ----------
def cmd_conferir(a):
    V = carregar_verif(a.verif) if a.verif and os.path.exists(a.verif) else {}
    casos = []
    for name, d in load_docs(a.maos):
        for l in d.get("linhas", []):
            if l["id"] in V: continue
            if l["situacao"] in ("Sem resposta", "Aguardando", "Só a IA respondeu") or (l.get("espera_min") or 0) >= 60:
                casos.append({"id": l["id"], "contato": l["contato"], "dia": l["dia"], "hora": l["hora"]})
    casos = list({c["id"]: c for c in casos}.values())[: int(a.max)]
    os.makedirs(a.out, exist_ok=True)
    n = 0
    for i in range(0, len(casos), 50):
        json.dump(casos[i:i + 50], open(os.path.join(a.out, f"v_{i // 50}.json"), "w"), ensure_ascii=False); n += 1
    print(json.dumps({"casos": len(casos), "lotes": n}, ensure_ascii=False))

def cmd_verifdoc(a):
    V = carregar_verif(a.res)
    ls = [{k: v for k, v in l.items() if k in ("id", "tipo", "msg", "humano", "ia")} for l in V.values()]
    json.dump({"linhas": ls}, open(a.out, "w"), ensure_ascii=False)
    print(json.dumps({"linhas": len(ls), "tipos": dict(collections.Counter(l.get("tipo") for l in ls))}, ensure_ascii=False))


# ---------- comando universo: todo lead (não comprador) de ISD/Protagon que escreveu no dia ----------
def cmd_universo(a):
    dia = a.dia
    ini15 = (dt.date.fromisoformat(dia) - dt.timedelta(days=14)).isoformat()
    om = {o["id"]: produto_da_origem(o) for o in origins_of(a.origins)}
    chats = collections.defaultdict(collections.Counter)
    for r in rows_of(a.chats):
        d = (r.get("Message.createdAt.day") or r.get("Message.createdAt") or "")[:10]
        if d == dia and r.get("Contact.id") and r.get("Chat.id"): chats[r["Contact.id"]][r["Chat.id"]] += int(r.get("Message.count") or 0)
    prods = collections.defaultdict(set); comprou = collections.defaultdict(set)
    for r in rows_of(a.q3):
        c = r.get("Contact.id"); oid = r.get("Origin.id") or ""
        if oid not in om: continue
        p, nao = om[oid]
        if not p: continue
        prods[c].add(p)
        if r.get("Deal.status") == "WON" and not nao:
            w = (r.get("Deal.wonAt") or "")[:10]
            if w and w > "1970" and w <= dia: comprou[c].add(p)
    sel = []
    for c, ch in chats.items():
        ps = sorted(p for p in prods.get(c, ()) if p not in comprou[c])
        if ps: sel.append({"contact": c, "produto": ps, "chats": [x for x, _ in ch.most_common(2)]})
    os.makedirs(a.out, exist_ok=True)
    n = int(a.tam)
    for i in range(0, len(sel), n):
        json.dump(sel[i:i + n], open(os.path.join(a.out, f"u_{i // n:02d}.json"), "w"), ensure_ascii=False)
    print(json.dumps({"dia": dia, "escreveram": len(chats), "universo": len(sel), "lotes": (len(sel) + n - 1) // n,
                      "compradores_fora": sum(1 for c in chats if comprou[c] and not (prods[c] - comprou[c]))}, ensure_ascii=False))

# ---------- comando maos2: levantadas de mão pelo que o lead escreveu ----------
TIPOS = {"quer_conversar": "Quer conversar", "reengajou": "Só reengajou", "saiu": "Saiu", "auto_resposta": "Resposta automática", "outro": "Outro", "automacao_atendeu": "Automação atendeu", "nao_pedia": "Não pedia resposta", "suporte": "Suporte"}
def cmd_maos2(a):
    P = lambda s_: dt.datetime.fromisoformat(s_[:19])
    corte = P(a.corte)
    hum = collections.defaultdict(list)
    for f in a.q6.split(","):
        for r in rows_of(f):
            t = r.get("Message.createdAt.minute") or r.get("Message.createdAt")
            if t and r.get("Contact.id"): hum[r["Contact.id"]].append((P(t), nome_vend(r.get("User.name"))))
    for v in hum.values(): v.sort()
    dono = {}
    for f in a.donos.split(","):
        for r in rows_of(f):
            c = r.get("Contact.id"); u = r.get("User.name")
            if not c or not u or r.get("Deal.status") not in ("OPEN", None): continue
            oid = r.get("Origin.id"); prod = "ISD" if oid in ISD_PRE else "Protagon"
            k = (c, prod); t = r.get("Deal.createdAt") or ""
            if k not in dono or t > dono[k][0]: dono[k] = (t, nome_vend(u))
    res = {}
    for f in sorted(glob.glob(os.path.join(a.res, "**", "*.json*"), recursive=True)):
        try:
            if f.endswith(".jsonl"): ls = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
            else:
                d = json.load(open(f, encoding="utf-8"))
                if d.get("dia") != a.dia: continue
                ls = d.get("linhas", [])
        except Exception: continue
        for r in ls:
            if r.get("contact") and r.get("produto"): res[(r["contact"], r["produto"])] = r
    linhas = []
    for (c, prod), r in res.items():
        tipo = TIPOS.get(r.get("tipo"), "Outro")
        hora = (r.get("hora") or "")[:5]
        if not hora or ":" not in hora: continue
        tm = P(f"{a.dia}T{hora}:00")
        hs = hum.get(c, [])
        antes = [h for h in hs if tm - dt.timedelta(minutes=60) <= h[0] < tm]
        depois = [h for h in hs if h[0] >= tm]
        own = dono.get((c, prod), (None, None))[1]
        esp = None
        if tipo != "Quer conversar": sit = "—"; vend = (depois[0][1] if depois else own) or "Sem dono"
        elif depois:
            esp = round(util_min(tm, depois[0][0])); sit = faixa(esp); vend = depois[0][1]
        else:
            vend = own or "Sem dono"
            sit = "Só a IA respondeu" if r.get("ia") else ("Sem resposta" if util_min(tm, corte) > 15 else "Aguardando")
        linhas.append({"id": "h-" + hashlib.sha1((c + prod + a.dia).encode()).hexdigest()[:10], "dia": a.dia, "hora": hora, "produto": prod,
                       "tipo": tipo, "msg": s(r.get("msg"))[:90], "vendedor": vend, "situacao": sit, "espera_min": esp,
                       "fora_horario": "Não" if no_horario(tm) else "Sim", "conversa": rid(c, prod), "contato": c,
                       "conferido_ate": corte.strftime("%Y-%m-%dT%H:%M")})
    os.makedirs(a.out, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
    fn = os.path.join(a.out, f"maos_{a.dia.replace('-', '')}_{stamp}.json")
    json.dump({"dia": a.dia, "metodo": "mensagem", "linhas": linhas}, open(fn, "w"), ensure_ascii=False)
    q = [l for l in linhas if l["tipo"] == "Quer conversar"]
    print(json.dumps({"dia": a.dia, "arquivo": os.path.basename(fn), "classificados": len(linhas),
                      "tipos": dict(collections.Counter(l["tipo"] for l in linhas)),
                      "quer_conversar": dict(collections.Counter(l["situacao"] for l in q))}, ensure_ascii=False))


def cmd_classdoc(a):
    ls = []
    for f in sorted(glob.glob(os.path.join(a.res, "*.jsonl"))):
        for x in open(f, encoding="utf-8"):
            try: r = json.loads(x)
            except Exception: continue
            if r.get("contact"): ls.append({k: r.get(k) for k in ("contact", "produto", "tipo", "hora", "msg", "ia")})
    json.dump({"dia": a.dia, "linhas": ls}, open(a.out, "w"), ensure_ascii=False)
    print(json.dumps({"dia": a.dia, "linhas": len(ls), "tipos": dict(collections.Counter(l["tipo"] for l in ls))}, ensure_ascii=False))


def cmd_contatos(a):
    info = {}
    for f in a.q.split(","):
        for r in rows_of(f):
            if r.get("Contact.id"): info[r["Contact.id"]] = {"email": r.get("Contact.email") or "", "nome": r.get("Contact.name") or ""}
    cs = set()
    for name, d in load_docs(a.classe):
        if d.get("dia") == a.dia: cs |= {l["contact"] for l in d.get("linhas", []) if l.get("contact")}
    cs |= set(info)  # todos que escreveram no período da consulta (inclui compradores)
    ls = [{"contact": c, **info.get(c, {"email": "", "nome": ""})} for c in sorted(cs)]
    json.dump({"dia": a.dia, "linhas": ls}, open(a.out, "w"), ensure_ascii=False)
    print(json.dumps({"dia": a.dia, "contatos": len(ls), "com_email": sum(1 for l in ls if l["email"])}, ensure_ascii=False))


# ---------- comando revisar: aplica a 2ª leitura (auditoria) nas linhas de quem quis conversar ----------
TIPO_AUD = {"quer_conversar": "Quer conversar", "reengajou": "Só reengajou", "saiu": "Saiu", "auto_resposta": "Resposta automática", "outro": "Outro", "automacao_atendeu": "Automação atendeu", "nao_pedia": "Não pedia resposta", "suporte": "Suporte"}
def cmd_revisar(a):
    P = lambda s_: dt.datetime.fromisoformat(s_[:16].replace(" ", "T"))
    aud = {}
    for f in sorted(glob.glob(os.path.join(a.aud, "**", "*.json*"), recursive=True)):
        try:
            if f.endswith(".jsonl"): ls = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
            else: ls = json.load(open(f, encoding="utf-8")).get("linhas", [])
        except Exception: continue
        for l in ls:
            if l.get("id") and l.get("veredito"): aud[l["id"]] = l
    os.makedirs(a.out, exist_ok=True)
    tot = collections.Counter()
    for f in a.maos.split(","):
        d = json.load(open(f, encoding="utf-8"))
        for l in d["linhas"]:
            v = aud.get(l["id"])
            if not v: continue
            tot[v["veredito"]] += 1
            l["revisao"] = {"confirmado": "Confirmado na 2ª leitura", "corrigir": "Corrigido na 2ª leitura", "duvida": "Em dúvida: conferir no Clint"}.get(v["veredito"], "")
            if v.get("msg_lead"): l["msg"] = v["msg_lead"][:90]
            tc = TIPO_AUD.get(v.get("tipo_certo") or "")
            if v.get("tipo_ok") is False and tc and tc != "Quer conversar":
                l["tipo"] = tc; l["situacao"] = "—"; l["espera_min"] = None; tot["tipo_mudou"] += 1; continue
            if l.get("tipo") != "Quer conversar" and tc == "Quer conversar" and v["veredito"] == "corrigir":
                l["tipo"] = "Quer conversar"; tot["virou_quer"] += 1
            if l.get("tipo") != "Quer conversar": continue
            tm = dt.datetime.fromisoformat(f"{l['dia']}T{l['hora']}:00")
            nomes = re.findall(r"([A-ZÁÉÍÓÚÂÊÔÃÕ][a-zà-ú]+(?: [A-Z][a-zà-ú]+)?)\s+(?:\d|às)", v.get("troca_responsavel_depois") or "")
            resp = nomes[-1] if nomes else (v.get("responsavel_na_hora") or "")
            pch = v.get("primeiro_contato_humano") or ""
            if pch:
                th = P(pch)
                l["espera_min"] = round(util_min(tm, max(th, tm))); l["situacao"] = faixa(l["espera_min"])
                q = v.get("quem") or resp
                if q: l["vendedor"] = nome_vend(q)
                if v.get("contato_tipo") == "ligação": l["por_ligacao"] = "Sim"
            elif l.get("situacao") in ("Até 5 min", "5 a 15 min", "15 a 60 min", "1 a 4 h", "Mais de 4 h") and l.get("espera_min") is not None:
                tot["resposta_depois_da_revisao"] += 1  # o vendedor respondeu depois da 2ª leitura: vale a resposta medida agora
            else:
                l["situacao"] = "Só a IA respondeu" if v.get("ia_respondeu") else "Sem resposta"; l["espera_min"] = None
                if not resp and l.get("vendedor") not in (None, "", "Sem dono", "Responsável não identificado", "Sem responsável confirmado"): l["dono_hoje"] = l["vendedor"]
                l["vendedor"] = "Agente de IA" if resp.lower().startswith(("fábio", "fabio")) else (nome_vend(resp) if resp else "Sem responsável confirmado")
        d["revisado"] = True
        fn = os.path.join(a.out, os.path.basename(f).replace(".json", "_rev.json"))
        json.dump(d, open(fn, "w"), ensure_ascii=False)
    print(json.dumps(dict(tot), ensure_ascii=False))

def cmd_pendentes(a):
    feitos = set()
    for name, d in load_docs(os.path.join(a.store, "radar_dias")):
        if d.get("dia"): feitos.add(d["dia"])
    ate = dt.date.fromisoformat(a.ate)
    ult = max((dt.date.fromisoformat(x) for x in feitos), default=ate - dt.timedelta(days=1))
    dias = []
    d = ult + dt.timedelta(days=1)
    while d <= ate:
        dias.append(d.isoformat()); d += dt.timedelta(days=1)
    print(json.dumps({"ultimo_dia_na_base": ult.isoformat(), "processar": dias[-3:], "pulados_por_limite": dias[:-3]}, ensure_ascii=False))


# ---------- origens: leads por canal e vendas do comercial ----------
ORIG_LEAD = {"5f2a86db-a0cc-4aec-8e81-dec8f3606017": "ISD", "0d22217f-063a-4f85-a276-0b4277d481ae": "Protagon",
             "395e2051-56f6-4916-813c-5c35955e7f28": "Protagon", "d779c2f3-daaa-4bbb-b08b-f0343ba5cef1": "Protagon"}
ORIG_COMPRA = {"282cc83d-147c-4e75-8f21-a8088f56f8e6": "ISD", "5196ccf0-e781-499d-9694-fe8a4b95ce85": "Protagon"}
VENDEDOR_COD = {"priteganif": "Pry", "emanoelle": "Emanoelle", "furlan": "Gabriel Furlan", "dirceubf": "Dirceu",
                "workshop-pd3-dirceubf": "Dirceu", "danilonc": "Danilo", "danilon": "Danilo", "vaniag": "Vânia",
                "gabrielaf": "Gabriela", "suellenmm": "Suellen", ".suellenmm": "Suellen", "suellen": "Suellen",
                "jaldo": "Jaldo", "inaiara": "Inaiara", "adeviana": "Adeilson", "adevianna": "Adeilson",
                "carinaf": "Carina", "victoria": "Victoria"}

def _norm(s):
    import unicodedata
    return unicodedata.normalize("NFKD", (s or "").strip()).encode("ascii", "ignore").decode().upper()

def _utm_camp(u):
    """utm_campaign que é nome de campanha de verdade (não vazio, não genérico como 'wendell')."""
    return _utm_ok(u) and _norm(u) not in UTM_GENERICA

def _utm_ok(u):
    U = _norm(u)
    return bool(U) and U not in ("SEM DADOS", "CAMPAIGN") and "{{" not in U

UTM_GENERICA = ("WENDELL", "KARINA", "PROTAGON", "ISD")

def canal_utm(utm, medium="", source=""):
    """Canal pela campanha do anúncio (utm_campaign), que é a fonte mais confiável. Devolve '' se não der para dizer."""
    U = _norm(utm)
    if _utm_ok(utm) and U not in UTM_GENERICA:
        if "INLEAD" in U: return "Inlead · venda direta" if ("VENDA DIRETA" in U or "[VENDA]" in U or "[VENDAS]" in U) else "Inlead · geração de demanda"
        if "VENDA DIRETA" in U or "PAGINA DE VENDA" in U: return "Venda direta (página de vendas)"
        if "FORMS NATIVO" in U or "FORMS-NATIVO" in U or "[FORMS]" in U or " FORMS]" in U: return "Formulário nativo (Meta)"
        if "WEBINARIO" in U or "WEBNARIO" in U: return "Webinário"
        if "PAGINA COMERCIAL" in U or "PG COMERCIAL" in U: return "Página comercial"
        if "METEORICO" in U: return "Meteórico (Protagon)"
        if "REMARKETING" in U or "RMKT" in U: return "Remarketing"
        if "[WHATSAPP]" in U: return "Anúncio para WhatsApp"
        if "INDICACAO" in U: return "Indicação"
    return ""

def _organico(utm, medium):
    return _norm(medium) in ("SOCIAL", "BIO", "MANYCHAT", "ORGANIC", "ORGANICO")

def _pago_sem_campanha(utm, medium):
    return _norm(medium) in ("PAID", "CPC", "PAGO") or _norm(utm) in UTM_GENERICA

def canal_de(acao, utm="", medium="", source="", fonte=""):
    c = canal_utm(utm, medium, source)
    if c: return c
    a = _norm(acao)
    if "-GD-" in a or "INLEAD" in a or "-ILD" in a:
        return "Inlead · geração de demanda" if ("-GD-" in a or a.startswith("INLEAD") or re.search(r"\bE0\d\d - INLEAD", a)) else "Inlead · venda direta"
    if _organico(utm, medium): return "Orgânico (redes do Wendell)"
    if not a:
        if _pago_sem_campanha(utm, medium): return "Tráfego pago sem campanha"
        return "Criado à mão no Clint" if _norm(fonte) == "MANUAL" else "Sem origem registrada"
    if "FORMSMETA" in a or "FORMS" in a or "FORM META" in a: return "Formulário nativo (Meta)"
    if "VENDA DIRETA" in a or "-VDD" in a or "-VD-" in a: return "Venda direta (página de vendas)"
    if "WEBNARIO" in a or "WEBINARIO" in a or "WORKSHOP" in a or a.startswith("LIVE") or " WEB-" in a or a.startswith("WEB "): return "Webinário"
    if "METEORICO" in a or a.endswith("-MET"): return "Meteórico (Protagon)"
    if "REMARKETING" in a: return "Remarketing"
    if "COMERCIAL" in a: return "Página comercial"
    if "DISPARO" in a: return "Disparo (lead criado pelo disparo)"
    if "WHATSAPP" in a: return "WhatsApp (chamou direto)"
    if "INDICACAO" in a: return "Indicação"
    # nomes de conjunto do formulário nativo ("ISD-RIB-E018 - 29 -07", "PRO-JOI-E035 - V3", "ISD-SP-E020 - M10K"):
    # quando o mesmo nome vem com campanha, 100% são [FORMS NATIVO]
    if re.match(r"^(ISD|PRO)-([A-Z]{2,3}-E\d+|E\d+-[A-Z]{2,3})\s*-\s*(V\d+|M\d+K|\d+\s*-\s*\d+|FORMS?\s*\d*)\b", a): return "Formulário nativo (Meta)"
    if re.match(r"^(ISD|PRO)-([A-Z]{2,3}-E\d+|E\d+-[A-Z]{2,3})\b", a): return "Página de captura (sem campanha)"
    return "Outros"

OUTRO_PRODUTO = ("COLISEU", "DIGNUS", "5 LIBERDADES", "5L-")

# ---------- regra do time (30/out): Ação do contato é o campo principal; Origem do negócio/UTM é a dupla checagem ----------
SEM_CANAL = ("Outros", "Página de captura (sem campanha)", "Sem origem registrada", "Criado à mão no Clint",
             "Disparo (lead criado pelo disparo)", "Tráfego pago sem campanha", "Sem lead no Clint", "Venda sem registro no Clint")
# As 11 origens do dash (definidas pelo Diego em 30/out). Disparo não é origem: o lead já estava na base por alguma delas.
ORIGENS = ("Formulário nativo (Meta)", "WhatsApp (chamou direto)", "Orgânico (redes do Wendell)", "Meteórico (Protagon)", "Webinário",
           "Inlead · geração de demanda", "Inlead · venda direta", "Venda direta (página de vendas)", "Página comercial", "Indicação", "Remarketing")
ORIGEM_PADRAO = "Origem não identificada"  # regra do Diego (30/out): o que não se encaixa nas 11 origens após todas as checagens
def origem_final(cn):
    """Leva qualquer rótulo para uma das 11 origens. Só traduz rótulos equivalentes; o que não tem equivalente devolve ''."""
    eq = {"Anúncio para WhatsApp": "WhatsApp (chamou direto)", "Acesso direto (sem rastreio)": "Venda direta (página de vendas)",
          "Oferta para alunos": "Venda direta (página de vendas)"}
    cn = eq.get(cn, cn)
    return cn if cn in ORIGENS else ""
CANAIS_PAGOS = ("Formulário nativo (Meta)", "Meteórico (Protagon)", "Inlead · geração de demanda", "Inlead · venda direta", "Remarketing", "Anúncio para WhatsApp")

def acao_valida(a):
    a = (a or "").strip()
    return a if a and not any(x in _norm(a) for x in OUTRO_PRODUTO) else ""

def trafego_de(canal, utm="", medium=""):
    """De onde veio o tráfego: Pago, Social (orgânico), Disparo, WhatsApp, Indicação ou Não identificado."""
    if _organico(utm, medium): return "Social (orgânico)"
    if _utm_camp(utm) or _norm(medium) in ("PAID", "CPC"): return "Tráfego pago"
    if canal in CANAIS_PAGOS: return "Tráfego pago"
    if canal == "Orgânico (redes do Wendell)": return "Social (orgânico)"
    if canal.startswith("Disparo"): return "Disparo (base própria)"
    if canal.startswith("WhatsApp"): return "WhatsApp (chamou direto)"
    if canal == "Indicação": return "Indicação"
    return "Não identificado"

def canal_lead(acao_contato, origem, utm="", medium="", source="", fonte=""):
    """Devolve (canal, fonte_do_canal, confere). Ação do contato primeiro; Origem/UTM como dupla checagem e reserva."""
    a = acao_valida(acao_contato)
    ca = canal_de(a) if a else ""
    co = canal_de(origem, utm, medium, source, fonte)
    if ca and ca not in SEM_CANAL:
        return ca, "acao", (None if co in SEM_CANAL else ca == co)
    return co, "origem", None

def _rank_canal(cn):
    if cn.startswith("Inlead"): return 3
    if cn in ("Sem origem registrada", "Criado à mão no Clint", "Outros"): return 0
    if cn in ("Venda direta (página de vendas)", "Orgânico (redes do Wendell)", "Disparo (lead criado pelo disparo)", "WhatsApp (chamou direto)", "Tráfego pago sem campanha"): return 1
    return 2

def _hash(c): return hashlib.sha1(("o" + c).encode()).hexdigest()[:10]

# ---------- rastreio da compra (sck) e negócios marcados com o código HP ----------
import urllib.parse
VEND_SCK = {"priteganif","emanoelle","furlan","dirceubf","vaniag","gabrielaf","inaiara","jaldo","danilonc","suellenmm","suellen","adeviana","carinaf"}
def sck_info(s):
    """(campanha, codigo) do campo sck da compra. Link de vendedor ou vazio -> ('','')."""
    s = (s or "").strip()
    if not s or s.lower() in ("sem dados",): return "", ""
    if s.startswith("["):
        try: a = [urllib.parse.unquote_plus(str(x)) for x in json.loads(s)]
        except Exception: a = [s]
        if len(a) >= 2 and a[0].lower() not in ("organico", "acesso_direto", "wc"): return a[1], ""
        if len(a) >= 2: return "", a[0].lower()
        x = a[0]
        if x.lower() in VEND_SCK or x.lower() == "sem dados": return "", ""
        return "", x
    if "|c=" in s or s.startswith("s="):
        m = re.search(r"(?:^|\|)c=([^|]+)", s)
        return (m.group(1) if m else ""), ("acesso_direto" if "acesso_direto" in s else "")
    if s.count(",") >= 2 and not s.startswith("WC-"):
        p = s.split(","); return p[2], ""
    if "|" in s: return "", s.split("|")[0]
    return "", s
def canal_codigo(cod):
    """Códigos de rastreio da Virtus (WC-<tipo>-<canal>...) -> (canal, trafego)."""
    u = (cod or "").upper()
    if not u: return "", ""
    if "-MET-" in u or u.startswith("MET"): return "Meteórico (Protagon)", "Disparo (base própria)" if "-CRM-" in u else "Tráfego pago"
    if "-WEB-" in u or "WEBNARIO" in u: return "Webinário", "Disparo (base própria)" if ("-CRM-" in u or "-GRU-" in u) else "Social (orgânico)"
    if "-SOC" in u or "BIO" in u or u in ("ORGANICO",): return "Orgânico (redes do Wendell)", "Social (orgânico)"
    if "OFEALU" in u or "-EVE-" in u: return "Venda direta (página de vendas)", "Disparo (base própria)"
    if u == "ACESSO_DIRETO": return "Venda direta (página de vendas)", "Não identificado"
    return "", ""


def _lead_abriu(created, first):
    """A conversa foi aberta pelo próprio contato: a 1ª mensagem dele chegou até 5 min depois da abertura (não foi disparo nem vendedor)."""
    if not first or first[:4] == "1970" or not created: return False
    try:
        c = dt.datetime.fromisoformat(created[:19]); f = dt.datetime.fromisoformat(first[:19])
    except ValueError: return False
    return (f - c).total_seconds() <= 300

def cmd_origensdia(a):
    """--leads: negócios de lead criados no dia (arquivos separados por vírgula); --vendas: compras ganhas no dia;
    --hist: negócios de lead (todas as datas) dos contatos que compraram; saída: documento do dia."""
    dia = a.dia
    leads = []
    for p in [x for x in a.leads.split(",") if x]: leads += rows_of(p)
    melhor = {}; ordem = []
    for r in sorted(leads, key=lambda r: r.get("Deal.createdAt", "")):
        o = r.get("Deal.originId"); prod = ORIG_LEAD.get(o)
        if not prod or (r.get("Deal.createdAt") or "")[:10] != dia: continue
        c = r.get("Deal.contactId") or ""
        k = (c, prod)
        acao_c = acao_valida(r.get("ContactFields.field_acao"))
        origem = (r.get("DealFields.field_origem") or "").strip()
        utm = (r.get("DealFields.field_utm_campaign") or "").strip(); med = r.get("DealFields.field_utm_medium") or ""
        cn, fonte_cn, confere = canal_lead(acao_c, origem, utm, med, r.get("DealFields.field_utm_source"), r.get("Deal.sourceLabel"))
        item = {"c": _hash(c), "cid": c, "produto": prod, "acao": (acao_c or origem)[:80], "origem": origem[:80], "campanha": (utm if _utm_camp(utm) else "")[:60],
                "canal": cn, "fonte_canal": fonte_cn, "confere": confere, "trafego": trafego_de(cn, utm, med)}
        # uma entrada por pessoa e produto no dia; se a pessoa entrou por mais de uma ação no dia, vale a mais específica (Inlead > campanha > genérica)
        if k not in melhor: melhor[k] = item; ordem.append(k)
        elif _rank_canal(item["canal"]) > _rank_canal(melhor[k]["canal"]): melhor[k] = item
    out_l = [melhor[k] for k in ordem]
    # leads sem origem de tráfego: procura nos outros negócios de lead do mesmo contato (qualquer data) — regra do time
    busca = collections.defaultdict(list)
    for p in [x for x in (getattr(a, "busca", "") or "").split(",") if x]:
        for r in rows_of(p):
            busca[r.get("Deal.contactId")].append(r)  # qualquer funil: a UTM de qualquer negócio do contato vale (3ª checagem)
    if getattr(a, "precisa", ""):
        # contatos sem origem de tráfego (para a consulta de histórico da rotina)
        json.dump(sorted({it["cid"] for it in out_l if it["trafego"] not in ("Tráfego pago", "Social (orgânico)") and it["cid"]}), open(a.precisa, "w"))
    for it in out_l:
        if it["trafego"] in ("Tráfego pago", "Social (orgânico)") and origem_final(it["canal"]): continue
        achados = []
        for r in busca.get(it["cid"], []):
            ac = acao_valida(r.get("ContactFields.field_acao")); og = (r.get("DealFields.field_origem") or "").strip()
            u = (r.get("DealFields.field_utm_campaign") or "").strip(); md = r.get("DealFields.field_utm_medium") or ""
            cn2 = canal_de(og, u, md, r.get("DealFields.field_utm_source"), "")
            if cn2 in SEM_CANAL and ac: cn2 = canal_de(ac)
            tr2 = trafego_de(cn2, u, md)
            if tr2 not in ("Tráfego pago", "Social (orgânico)"):
                cp, cd = sck_info(r.get("DealFields.field_sck_completo"))
                if cp: cn2, tr2, u = canal_de("", cp, "paid", "", ""), "Tráfego pago", cp
                elif cd:
                    c3, t3 = canal_codigo(cd)
                    if c3: cn2, tr2, og = c3, t3, cd
            achados.append(((r.get("Deal.createdAt") or "")[:10] <= dia, (r.get("Deal.createdAt") or ""), cn2, tr2, (u if _utm_camp(u) else og)[:60]))
        com_trafego = [x for x in achados if x[3] in ("Tráfego pago", "Social (orgânico)")]
        if com_trafego and it["trafego"] not in ("Tráfego pago", "Social (orgânico)"):
            _, _, cn2, tr2, ref = sorted(com_trafego)[-1]  # o mais recente até o dia; senão o mais recente depois
            it["trafego"] = tr2; it["trafego_achado"] = ref
            if not origem_final(it["canal"]) and origem_final(cn2):
                it["canal"] = origem_final(cn2); it["fonte_canal"] = "outro negócio do contato"
        if not origem_final(it["canal"]):
            # origem de verdade do contato (ex.: lead que voltou por disparo): o negócio mais recente até o dia com uma das 11 origens
            com_origem = [x for x in achados if origem_final(x[2])]
            if com_origem:
                _, _, cn2, tr2, ref = sorted(com_origem)[-1]
                it["canal"] = origem_final(cn2); it["fonte_canal"] = "outro negócio do contato"
                if it["trafego"] not in ("Tráfego pago", "Social (orgânico)") and tr2 in ("Tráfego pago", "Social (orgânico)"):
                    it["trafego"] = tr2; it["trafego_achado"] = ref
    if getattr(a, "resta", ""):
        json.dump(sorted({it["cid"] for it in out_l if it["trafego"] not in ("Tráfego pago", "Social (orgânico)") and it["cid"]}), open(a.resta, "w"))
    # 4ª checagem: lead sem origem nenhuma cujo contato escreveu no WhatsApp até o dia -> "WhatsApp (chamou direto)"
    chl = collections.defaultdict(list)
    for p in [x for x in (getattr(a, "chats", "") or "").split(",") if x]:
        for r in rows_of(p):
            if r.get("Contact.id") and _lead_abriu(r.get("Chat.createdAt") or "", r.get("Chat.firstCustumerMessageAt") or ""):
                chl[r["Contact.id"]].append(r.get("Chat.firstCustumerMessageAt") or "")
    for it in out_l:
        if not origem_final(it["canal"]):
            fm = [x for x in chl.get(it["cid"], []) if x and x[:4] != "1970" and x[:10] <= dia]
            if fm:
                it["canal"] = "WhatsApp (chamou direto)"; it["fonte_canal"] = "1ª conversa no WhatsApp"
                if it["trafego"] not in ("Tráfego pago", "Social (orgânico)"): it["trafego"] = "WhatsApp (chamou direto)"
    if getattr(a, "semcanal", ""):
        json.dump(sorted({it["cid"] for it in out_l if not origem_final(it["canal"]) and it["cid"]}), open(a.semcanal, "w"))
    if getattr(a, "auditoria", ""):
        json.dump([{"cid": it["cid"], "dia": dia, "produto": it["produto"], "canal": it["canal"], "acao": it.get("acao", ""), "origem": it.get("origem", ""),
                    "campanha": it.get("campanha", ""), "fonte": it.get("fonte_canal", ""), "trafego": it["trafego"]} for it in out_l], open(a.auditoria, "w"), ensure_ascii=False)
    for it in out_l:
        if origem_final(it["canal"]): it["canal"] = origem_final(it["canal"])
        else:
            # último recurso: nenhum registro de origem no Clint -> o contato chegou direto ao time (criado à mão, sem Ação, sem UTM, sem conversa)
            it["origem_original"] = it["canal"]; it["canal"] = ORIGEM_PADRAO; it["fonte_canal"] = "sem registro (padrão)"
            if it["trafego"] not in ("Tráfego pago", "Social (orgânico)"): it["trafego"] = "Não identificado"
    for it in out_l:
        # documento compacto (limite de 256 KB por documento): no método v2, campo ausente = valor padrão
        it.pop("cid", None); it.pop("origem", None)
        if it.get("acao"): it.pop("campanha", None)
        if it.get("fonte_canal") == "acao": it.pop("fonte_canal")
        if it.get("confere") is None: it.pop("confere", None)
        if it.get("trafego") == "Tráfego pago": it.pop("trafego")
    hist = collections.defaultdict(list)
    for r in rows_of(a.hist):
        prod = ORIG_LEAD.get(r.get("Deal.originId"))
        if prod:
            ac = (r.get("DealFields.field_origem") or "").strip(); utm = (r.get("DealFields.field_utm_campaign") or "").strip()
            cn = canal_de(ac, utm, r.get("DealFields.field_utm_medium"), r.get("DealFields.field_utm_source"), r.get("Deal.sourceLabel"))
            hist[r.get("Deal.contactId")].append((r.get("Deal.createdAt") or "", prod, ac, cn, utm if _utm_camp(utm) else ""))
    out_v = []; dup = set()
    for r in rows_of(a.vendas):
        cod = (r.get("DealFields.field_parametro_1") or "").strip().lower()
        vend = VENDEDOR_COD.get(cod)
        prod = ORIG_COMPRA.get(r.get("Deal.originId"))
        won = (r.get("Deal.wonAt") or "")
        pf = _norm(r.get("DealFields.field_produto"))
        if pf and pf not in ("ISD", "PROTAGON"): continue  # Coliseu/Dignus vendidos no funil de compra de ISD não contam
        if not vend or not prod or won[:10] != dia: continue
        c = r.get("Deal.contactId") or ""; val = round(int(r.get("Deal.value") or 0) / 100, 2)
        k = (c, val, won[:10])
        if k in dup: continue
        dup.add(k)
        cand = sorted([h for h in hist.get(c, []) if h[0] <= won], reverse=True)
        mesmo = [h for h in cand if h[1] == prod] or cand
        boas = sorted([h for h in mesmo if h[3] not in ("Sem origem registrada", "Criado à mão no Clint")], key=lambda h: (h[0][:16], _rank_canal(h[3])), reverse=True)
        h0 = boas[0] if boas else (mesmo[0] if mesmo else None)
        acao = h0[2] if h0 else ""
        out_v.append({"c": _hash(c), "produto": prod, "acao": acao, "campanha": (h0[4] if h0 else "")[:60], "canal": h0[3] if h0 else "Sem lead no Clint",
                      "valor": val, "vendedor": vend, "lead_desde": (mesmo[-1][0][:10] if mesmo else "")})
    doc = {"dia": dia, "metodo": "origens_v2", "leads": out_l, "vendas": out_v}
    json.dump(doc, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    cn = collections.Counter(x["canal"] for x in out_l)
    print(json.dumps({"dia": dia, "leads": len(out_l), "vendas": len(out_v), "faturamento": round(sum(x["valor"] for x in out_v), 2), "por_canal": cn.most_common()}, ensure_ascii=False))

# ---------- vendas do comercial pela planilha "Backup vendas" (fonte oficial do comercial) ----------
PLAN_PROD = {"IMERSAO": "ISD", "PROTAGON": "Protagon"}

def _brl(x):
    x = (x or "").strip()
    return round(float(x.replace(".", "").replace(",", ".")), 2) if x else 0.0

def _dia_br(d):
    dd, mm, aa = [int(p) for p in d.strip().split("/")]
    return f"{aa:04d}-{mm:02d}-{dd:02d}"

def _vend(n):
    n = (n or "").strip()
    return n[:1].upper() + n[1:] if n else "—"

def cmd_vendasplan(a):
    """--csv: planilha exportada em CSV; --hp: negócios do Clint com o código HP (Deal.contactId/originId);
    --hist: negócios de lead (arquivos separados por vírgula); --desde/--ate: período; --out: documento."""
    import csv
    linhas = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    hp = collections.defaultdict(list)
    for r in rows_of(a.hp): hp[(r.get("DealFields.field_cod_da_transferencia") or "").strip()].append(r)
    contato = {}
    for cod, v in hp.items():
        cs = sorted({r["Deal.contactId"] for r in v if r.get("Deal.originId") in ORIG_COMPRA}) or sorted({r["Deal.contactId"] for r in v})
        contato[cod] = cs[0] if cs else ""
    hist = collections.defaultdict(dict); acao_ct = {}; utm_any = collections.defaultdict(list); acao_raw = {}
    for p in [x for x in a.hist.split(",") if x]:
        for r in rows_of(p):
            # UTM/rastreio de qualquer negócio do contato (3ª checagem)
            u0 = (r.get("DealFields.field_utm_campaign") or "").strip(); md0 = r.get("DealFields.field_utm_medium") or ""
            src0 = (r.get("DealFields.field_utm_source") or "").strip()
            cand = None
            if (u0 and _norm(u0) != "SEM DADOS") or _organico(u0, md0):
                cn0 = canal_de("", u0, md0, src0, ""); cand = (cn0, trafego_de(cn0, u0, md0), u0)
            else:
                cp0, cd0 = sck_info(r.get("DealFields.field_sck_completo"))
                if cp0: cand = (canal_de("", cp0, "paid", "", ""), "Tráfego pago", cp0)
                elif cd0:
                    c0, t0 = canal_codigo(cd0)
                    if c0: cand = (c0, t0, cd0)
            if cand and cand[0] not in SEM_CANAL and cand[1] != "Não identificado":
                utm_any[r.get("Deal.contactId")].append(((r.get("Deal.createdAt") or "")[:19],) + cand)
            av = acao_valida(r.get("ContactFields.field_acao"))  # Ação do contato: vale de qualquer negócio (inclusive a própria compra)
            if (r.get("ContactFields.field_acao") or "").strip(): acao_raw[r.get("Deal.contactId")] = r["ContactFields.field_acao"].strip()
            if av: acao_ct[r.get("Deal.contactId")] = av
            prod = ORIG_LEAD.get(r.get("Deal.originId"))
            if not prod: continue
            ac = (r.get("DealFields.field_origem") or "").strip(); utm = (r.get("DealFields.field_utm_campaign") or "").strip()
            md = r.get("DealFields.field_utm_medium") or ""
            cn = canal_de(ac, utm, md, r.get("DealFields.field_utm_source"), r.get("Deal.sourceLabel"))
            hist[r.get("Deal.contactId")][r["Deal.id"]] = ((r.get("Deal.createdAt") or "")[:19], prod, ac, cn, utm if _utm_ok(utm) else "", trafego_de(cn, utm, md))
    chv = collections.defaultdict(list)
    for p in [x for x in (getattr(a, "chats", "") or "").split(",") if x]:
        for r in rows_of(p):
            if r.get("Contact.id") and _lead_abriu(r.get("Chat.createdAt") or "", r.get("Chat.firstCustumerMessageAt") or ""):
                chv[r["Contact.id"]].append(r.get("Chat.firstCustumerMessageAt") or "")
    out = []; fora = collections.Counter()
    for i, r in enumerate(linhas):
        try: dia = _dia_br(r.get("Data de Venda") or "")
        except Exception: continue
        if not (a.desde <= dia <= a.ate): continue
        prod = PLAN_PROD.get(_norm(r.get("Produto")))
        if not prod: fora[_norm(r.get("Produto"))] += 1; continue
        cod = (r.get("Cod Transação") or "").strip()
        c = contato.get(cod, "")
        trafego, fonte_cn = "Não identificado", ""
        if not c:
            canal, acao, camp, desde = "Venda sem registro no Clint", "", "", ""
        else:
            cand = sorted([h for h in hist.get(c, {}).values() if h[0][:10] <= dia], reverse=True)
            mesmo = [h for h in cand if h[1] == prod] or cand
            boas = sorted([h for h in mesmo if h[3] not in SEM_CANAL], key=lambda h: (h[0][:16], _rank_canal(h[3])), reverse=True)
            # regra do time: o campo Ação do contato manda; vale quando bate com um negócio de lead dele até o dia da venda
            # (a Ação é a última do contato e pode ter mudado depois da compra, ex.: Coliseu — aí vale o negócio de lead)
            ca = canal_de(acao_ct[c]) if acao_ct.get(c) else ""
            pela_acao = [h for h in boas if ca and h[3] == ca]
            h0 = pela_acao[0] if pela_acao else (boas[0] if boas else (mesmo[0] if mesmo else None))
            fonte_cn = "acao" if pela_acao else ("origem" if h0 else "")
            canal = h0[3] if h0 else "Sem lead no Clint"; acao = h0[2] if h0 else ""; camp = (h0[4] if h0 else "")[:60]
            desde = mesmo[-1][0][:10] if mesmo else ""
            trafego = h0[5] if h0 else "Não identificado"
            if not origem_final(canal) and origem_final(ca):
                # comprador sem lead com origem: vale o campo Ação do contato (regra principal do time)
                canal, fonte_cn, acao = origem_final(ca), "acao", acao_ct[c]
                if trafego not in ("Tráfego pago", "Social (orgânico)"): trafego = trafego_de(canal)
            if trafego not in ("Tráfego pago", "Social (orgânico)"):
                # origem do tráfego: procura nos outros negócios de lead do contato (todos os leads vêm do tráfego ou do social)
                outros = sorted([h for h in hist.get(c, {}).values() if h[5] in ("Tráfego pago", "Social (orgânico)")], key=lambda h: (h[0][:10] <= dia, h[0]))
                if outros:
                    trafego = outros[-1][5]
                    if canal in SEM_CANAL or canal == "Sem lead no Clint": canal = outros[-1][3]; fonte_cn = "outro negócio do contato"
        # rastreio da própria compra (sck) e negócios com o mesmo código HP: vale se for mais específico que o achado pelo lead
        cands = []
        for r2 in hp.get(cod, []):
            cp, cd = sck_info(r2.get("DealFields.field_sck_completo"))
            if cp: cands.append((canal_de("", cp, "paid", "", ""), "Tráfego pago", cp))
            if cd:
                cn2, tr2 = canal_codigo(cd)
                if cn2: cands.append((cn2, tr2, cd))
            u2 = (r2.get("DealFields.field_utm_campaign") or "").strip()
            if u2 and _norm(u2) != "SEM DADOS":
                cn2 = canal_de("", u2, r2.get("DealFields.field_utm_medium"), r2.get("DealFields.field_utm_source"), "")
                cands.append((cn2, trafego_de(cn2, u2, r2.get("DealFields.field_utm_medium") or ""), u2))
        cands = [x for x in cands if x[0] and x[0] not in SEM_CANAL]
        if cands:
            b = max(cands, key=lambda x: _rank_canal(x[0]))
            if not origem_final(canal) or (_utm_camp(b[2]) and _rank_canal(b[0]) > _rank_canal(canal)):
                canal, camp, fonte_cn = b[0], (b[2] if _utm_camp(b[2]) else camp)[:60], "rastreio da compra"
                if b[1] in ("Tráfego pago", "Social (orgânico)") or trafego not in ("Tráfego pago", "Social (orgânico)"): trafego = b[1]
        # 3ª checagem: UTM/rastreio de qualquer negócio do contato (qualquer funil), o mais recente até a venda
        # 4ª: primeira conversa do contato no WhatsApp antes da venda
        if c and (not origem_final(canal) or trafego not in ("Tráfego pago", "Social (orgânico)")):
            r3 = None
            for dd, cn3, tr3, ref3 in sorted(utm_any.get(c, [])):
                if dd[:10] <= dia: r3 = (cn3, tr3, ref3)
            if r3:
                if not origem_final(canal) and origem_final(r3[0]):
                    canal, fonte_cn = origem_final(r3[0]), "UTM de outro negócio do contato"
                    if _utm_camp(r3[2]): camp = r3[2][:60]
                if trafego not in ("Tráfego pago", "Social (orgânico)"): trafego = r3[1]
            if not origem_final(canal):
                fm = [x for x in chv.get(c, []) if x and x[:4] != "1970" and x[:10] <= dia]
                if fm:
                    canal, fonte_cn = "WhatsApp (chamou direto)", "1ª conversa no WhatsApp"
                    if trafego not in ("Tráfego pago", "Social (orgânico)"): trafego = "WhatsApp (chamou direto)"
        orig0 = ""
        if origem_final(canal): canal = origem_final(canal)
        else:
            # último recurso: venda do comercial sem nenhum registro de origem no Clint -> cliente chegou direto ao vendedor
            orig0, canal, fonte_cn = canal, ORIGEM_PADRAO, "sem registro (padrão)"
        # Regra da Sales Ops (05/11/2026): vale a Ação do contato como está hoje, classificada pelas regras dela; sem Ação, as checagens acima
        cat_a, fonte_a, _ = categoria_final(acao_raw.get(c, ""), "") if c else (SEM_INFO, "", "")
        if cat_a != SEM_INFO:
            canal, fonte_cn, acao = cat_a, fonte_a, acao_raw.get(c, "")
        else:
            canal = RADAR_PARA_ACAO.get(canal, SEM_INFO)
        out.append({"dia": dia, "cod": cod, "c": _hash(c or cod), "produto": prod, "canal": canal, "acao": acao[:80], "campanha": camp,
                    "valor": _brl(r.get("Preço do Produto")), "vendedor": _vend(r.get("Vendedor")), "lead_desde": desde, "no_clint": bool(c),
                    "trafego": trafego, "fonte_canal": fonte_cn, "origem_original": orig0})
    doc = {"desde": a.desde, "ate": a.ate, "metodo": "planilha_comercial_v1", "fonte": "Google Sheets 'Backup vendas' (aba Comparacao mensal)", "vendas": out}
    json.dump(doc, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    tot = collections.defaultdict(lambda: [0, 0.0])
    for v in out: tot[v["produto"]][0] += 1; tot[v["produto"]][1] += v["valor"]
    print(json.dumps({"vendas": len(out), "por_produto": {k: [n, round(s, 2)] for k, (n, s) in tot.items()},
                      "sem_clint": sum(1 for v in out if not v["no_clint"]), "fora_isd_protagon": dict(fora),
                      "por_canal": collections.Counter(v["canal"] for v in out).most_common()}, ensure_ascii=False))

def origens_rows(store, desde):
    """Linhas do dataset origens a partir de radar_origens (o documento mais novo de cada dia vale)."""
    por_dia = {}
    # o documento mais novo de cada dia vale; os da régua da Sales Ops (origens_v3_salesops, desde 05/11/2026) sempre vencem os antigos
    for name, d in sorted(load_docs(os.path.join(store, "radar_origens")), key=lambda x: (x[1].get("metodo") == "origens_v3_salesops", x[0])):
        if d.get("dia") and d["dia"] >= desde:
            g = d.get("grupo"); prev = por_dia.get(d["dia"])
            if g and prev is not None and prev.get("grupo") == g:  # documento dividido em partes (limite de 256 KB por documento)
                prev = dict(prev); prev["leads"] = prev.get("leads", []) + d.get("leads", []); prev["vendas"] = prev.get("vendas", []) + d.get("vendas", [])
                por_dia[d["dia"]] = prev
            else: por_dia[d["dia"]] = d
    rows = []
    for dia, d in sorted(por_dia.items()):
        sem, rot = semana(dia)
        v2 = d.get("metodo") == "origens_v2"
        for i, l in enumerate(d.get("leads", [])):
            if v2:
                l.setdefault("fonte_canal", "acao"); l.setdefault("trafego", "Tráfego pago")
            rows.append({"id": f"l-{dia}-{i}", "tipo": "lead", "dia": dia, "semana": rot, "semana_ini": sem, "produto": l["produto"],
                         "canal": l["canal"], "acao": l.get("acao") or l.get("campanha") or "", "campanha": l.get("campanha", ""), "c": l["c"], "valor": None, "vendedor": "",
                         "trafego": l.get("trafego") or trafego_de(l["canal"]), "fonte_canal": l.get("fonte_canal", ""), "confere": l.get("confere"), "achado": bool(l.get("trafego_achado")), "lev": bool(l.get("lev")), "funil": l.get("funil", "")})
    # Vendas: a planilha do comercial é a fonte. Vale o documento mais novo; os dias que ela cobre substituem as vendas do Clint.
    plan = None
    pdir = os.path.join(store, "radar_vendas_plan")
    if os.path.isdir(pdir):
        docs = sorted(load_docs(pdir))
        if docs: plan = docs[-1][1]
    cobertos = set()
    if plan:
        d0 = dt.date.fromisoformat(max(plan["desde"], desde)); d1 = dt.date.fromisoformat(plan["ate"])
        while d0 <= d1: cobertos.add(d0.isoformat()); d0 += dt.timedelta(days=1)
        for i, v in enumerate(plan.get("vendas", [])):
            if v["dia"] not in cobertos: continue
            sem, rot = semana(v["dia"])
            rows.append({"id": f"p-{v['dia']}-{i}", "tipo": "venda", "dia": v["dia"], "semana": rot, "semana_ini": sem, "produto": v["produto"],
                         "canal": v["canal"], "acao": v.get("campanha") or v["acao"], "c": v["c"], "valor": v["valor"], "vendedor": v["vendedor"],
                         "trafego": v.get("trafego") or trafego_de(v["canal"]), "fonte_canal": v.get("fonte_canal", ""), "confere": None})
    for dia, d in sorted(por_dia.items()):
        if dia in cobertos: continue
        sem, rot = semana(dia)
        for i, v in enumerate(d.get("vendas", [])):
            rows.append({"id": f"v-{dia}-{i}", "tipo": "venda", "dia": dia, "semana": rot, "semana_ini": sem, "produto": v["produto"],
                         "canal": v["canal"], "acao": v.get("campanha") or v["acao"], "c": v["c"], "valor": v["valor"], "vendedor": v["vendedor"]})
    return rows

# ---------- reconf: reconfere os "Sem resposta" dos últimos dias com as mensagens do time até agora ----------
TIPO_EXCL = {"quiz": "Não pedia resposta", "suporte": "Suporte"}
def cmd_reconf(a):
    """Pega o documento mais novo de cada dia em radar_maos (o mesmo que o painel usa), procura a 1ª mensagem do time
    (qualquer conversa do contato, até agora) para quem está "Sem resposta"/"Só a IA"/"Aguardando" e grava um doc novo por dia.
    --excl: {id: quiz|suporte} = resposta a pergunta da automação ou suporte de quem já é aluno/ganhou ingresso (sai da conta)."""
    P = lambda s_: dt.datetime.fromisoformat(s_[:19])
    agora = P(a.agora)
    hum = collections.defaultdict(list)
    for f in a.msgs.split(","):
        for r in rows_of(f):
            t = r.get("Message.createdAt.minute") or r.get("Message.createdAt")
            if t and r.get("Contact.id"): hum[r["Contact.id"]].append((P(t), nome_vend(r.get("User.name"))))
    for v in hum.values(): v.sort()
    excl = json.load(open(a.excl)) if a.excl else {}
    latest = {}
    for name, d in sorted(load_docs(a.store), key=lambda x: x[0]):
        if d.get("dia") and d.get("metodo") == "mensagem": latest[d["dia"]] = (name, d)
    os.makedirs(a.out, exist_ok=True); tot = collections.Counter(); stamp = agora.strftime("%Y%m%d_%H%M")
    for dia, (name, d) in sorted(latest.items()):
        if dia < a.desde or (a.ate and dia > a.ate): continue
        mudou = False
        for l in d.get("linhas", []):
            l["conferido_ate"] = agora.strftime("%Y-%m-%dT%H:%M")
            if l["id"] in excl and l.get("tipo") == "Quer conversar":
                l["tipo"] = TIPO_EXCL[excl[l["id"]]]; l["situacao"] = "—"; l["espera_min"] = None
                l["revisao"] = "Tirado da conta na conferência de " + agora.strftime("%d/%m"); tot["excluido_" + excl[l["id"]]] += 1; mudou = True; continue
            if l.get("tipo") != "Quer conversar" or l.get("situacao") not in ("Sem resposta", "Só a IA respondeu", "Aguardando"): continue
            if not l.get("contato") or not l.get("hora"): continue
            tm = P(f"{dia}T{l['hora']}:00")
            dep = [h for h in hum.get(l["contato"], []) if h[0] >= tm - dt.timedelta(minutes=1)]
            if dep:
                l["espera_min"] = round(util_min(tm, max(dep[0][0], tm))); l["situacao"] = faixa(l["espera_min"])
                if dep[0][1]: l["vendedor"] = dep[0][1]
                l["revisao"] = "Respondido depois (conferido em " + agora.strftime("%d/%m") + ")"; tot["respondido_depois"] += 1; mudou = True
            elif l["situacao"] == "Aguardando" and util_min(tm, agora) > 15:
                l["situacao"] = "Sem resposta"; mudou = True
            else: tot["segue_sem_resposta" if l["situacao"] == "Sem resposta" else "segue_" + l["situacao"]] += 1
        fn = os.path.join(a.out, f"maos_{dia.replace('-', '')}_rev_{stamp}_rc.json")
        json.dump(d, open(fn, "w"), ensure_ascii=False); tot["docs"] += 1
    print(json.dumps(dict(tot), ensure_ascii=False))


# ---------- levantada de mão pela régua da Sales Ops (etapa atual do negócio de lead) ----------
ETAPAS_MAO = {"Conexão", "Negociação", "Follow automático", "Stand by", "Fechado", "Follow up", "Standby", "Compra fechada", "Compra Fechada"}
FUNIL_SESSAO = "395e2051-56f6-4916-813c-5c35955e7f28"  # Protagon: todo negócio nasce em "Conexão (sessão aberta)"; ali só conta da Negociação em diante
def cmd_levdoc(a):
    """--q: consultas (Contact.id, Deal.originId, Stage.name) dos negócios de lead criados no dia --dia; grava {dia, linhas:[{c, produto}]}."""
    vis = set()
    for f in [x for x in a.q.split(",") if x]:
        for r in rows_of(f):
            st = (r.get("Stage.name") or "").strip(); o = r.get("Deal.originId")
            if st not in ETAPAS_MAO or (o == FUNIL_SESSAO and st.startswith("Conexão")): continue
            if not r.get("Contact.id"): continue
            vis.add((_hash(r["Contact.id"]), "ISD" if o in ISD_PRE else "Protagon"))
    d = {"dia": a.dia, "metodo": "etapa_sales_ops", "linhas": [{"c": c, "produto": p} for c, p in sorted(vis)]}
    json.dump(d, open(a.out, "w"), ensure_ascii=False)
    print(json.dumps({"dia": a.dia, "levantadas": len(vis)}))

def levantadas_rows(store):
    por = {}
    for name, d in sorted(load_docs(os.path.join(store, "radar_lev"))):
        if d.get("dia"): por[d["dia"]] = d
    return [{"c": l["c"], "produto": l["produto"], "dia": dia} for dia, d in sorted(por.items()) for l in d.get("linhas", [])]


# ---------- Regras da Sales Ops (relatório semanal da Júlia), adotadas pelo Diego em 05/11/2026 ----------
# Lead = negócio (não pessoa). Base: ISD = funil Pré Checkout (5f2a86db); Protagon = Pré checkout (0d22217f) + Conexão (395e2051).
# Exclui e-mail com "@grupovirtus" e "teste" no nome ou e-mail; duplicado = mesmo telefone e e-mail, mesmos acao, origem e
# utm_content (todos preenchidos) e criação a menos de 1 min: fica o mais recente. Levantada de mão: Protagon = negócio no funil
# Conexão (qualquer etapa); ISD = etapa Conexão, Negociação, Follow automático, Stand by ou Fechado. Origem = Ação do contato como
# está no dia da extração, classificada pelas regras dela; sem Ação, vale a origem do negócio e depois as checagens do Radar
# (UTM, outros negócios do contato, conversa aberta pelo próprio contato). Tags não entram (decisão do Diego).
FUNIS_LEAD = {"5f2a86db-a0cc-4aec-8e81-dec8f3606017": "ISD", "0d22217f-063a-4f85-a276-0b4277d481ae": "Protagon",
              "395e2051-56f6-4916-813c-5c35955e7f28": "Protagon"}
FUNIL_CONEXAO_PRO = "395e2051-56f6-4916-813c-5c35955e7f28"
ETAPAS_LEV_ISD = {"Conexão", "Negociação", "Follow automático", "Stand by", "Fechado"}
ACAO_EXATA = {
    "PRO-JOI-E035 - V3": "FORMS META", "PRO-JOI-E035- V3": "FORMS META", "PRO-JOI-E035- V2": "FORMS META",
    "PRO-POA-E037 - V3": "FORMS META", "PRO-E039-SP-MET": "FORMS META", "ISD-E012 FORM META": "FORMS META",
    "ISD-SP-E020 - M10K": "FORMS META",
    "PRO-E038-GOI-GD-ILD": "INLEAD", "PRO-E037-POA-GD-ILD": "INLEAD", "PRO-E038-GOI-GD-ILD1": "INLEAD",
    "CTW-REMARKETING": "CLICK TO WHATSAPP", "Live 20:20 02/09": "LIVE 20:20",
    "PRO-E038-GOI-VDD-COM": "PÁGINA HÍBRIDA", "PRO-E037-POA-VDD-COM": "PÁGINA HÍBRIDA",
    "PRO-E038-GOI-COM": "CAPTURA COMERCIAL", "PRO-E039-SP-COM": "CAPTURA COMERCIAL", "ISD-E020-SP-COM": "CAPTURA COMERCIAL",
    "PRO-E037-POA-VDD-VND": "VENDA DIRETA", "PRO-E039-SP-VDD": "VENDA DIRETA", "PRO-E038-GOI-VDD-VND": "VENDA DIRETA",
    "PRO-E038-GOI-VDD": "VENDA DIRETA", "PRO-E038-GOI-VDD-VDN-VIP": "VENDA DIRETA",
    "WEBNARIO-28-10-26-PRO-MET-SP": "WEBNÁRIO",
    "COLISEU-INSCRIÇÕES-ABERTAS-30-10-26": "COLISEU-INSCRIÇÕES-ABERTAS-30-10-26", "COLISEU [CL-E001] - V1": "COLISEU",
    "isd_alphaville": "ALPHAVILLE", "indicacao isd": "INDICAÇÃO", "PROTAGON-OFERTA-ISD": "PROTAGON-OFERTA-ISD",
}
V8_CANAL = {"ILD": "INLEAD", "FNM": "FORMS META", "PGC": "CAPTURA COMERCIAL"}
V8_FUNIL = {"VDD": "VENDA DIRETA", "COM": "CAPTURA COMERCIAL", "MET": "METEÓRICO", "W5L": "WEBNÁRIO", "WTI": "WEBNÁRIO",
            "WIS": "WEBNÁRIO", "IND": "INDICAÇÃO"}
ACAO_PALAVRAS = [("FORMS", "FORMS META"), ("COMERCIAL", "CAPTURA COMERCIAL"), ("VENDA DIRETA", "VENDA DIRETA"), ("INLEAD", "INLEAD"),
                 ("ILD", "INLEAD"), ("WORKSHOP", "WEBNÁRIO"), ("WEB", "WEBNÁRIO"), ("METEORICO", "METEÓRICO"),
                 ("METEÓRICO", "METEÓRICO"), ("REMARKETING", "REMARKETING")]
RADAR_PARA_ACAO = {"Formulário nativo (Meta)": "FORMS META", "WhatsApp (chamou direto)": "WHATSAPP", "Anúncio para WhatsApp": "WHATSAPP",
                   "Orgânico (redes do Wendell)": "SOCIAL", "Meteórico (Protagon)": "METEÓRICO", "Webinário": "WEBNÁRIO",
                   "Inlead · geração de demanda": "INLEAD", "Inlead · venda direta": "INLEAD", "Venda direta (página de vendas)": "VENDA DIRETA",
                   "Acesso direto (sem rastreio)": "VENDA DIRETA", "Oferta para alunos": "VENDA DIRETA", "Página comercial": "CAPTURA COMERCIAL",
                   "Indicação": "INDICAÇÃO", "Remarketing": "REMARKETING"}
SEM_INFO = "SEM INFORMAÇÃO"

def acao_categoria(acao):
    """Categoria da Ação pelas regras da Sales Ops. '' -> SEM INFORMAÇÃO; valor sem regra -> None."""
    a = (acao or "").strip()
    if not a or _norm(a) in ("SEM INFORMACAO",): return SEM_INFO
    if "social" in a.lower(): return "SOCIAL"
    if a in ACAO_EXATA: return ACAO_EXATA[a]
    t = [x.strip().upper() for x in a.split("-")]
    if len(t) >= 4 and t[0] in ("PRO", "ISD"):
        resto = t[3:]
        for i in range(len(resto) - 1):
            if resto[i] == "VDD" and resto[i + 1] == "COM": return "PÁGINA HÍBRIDA"
        for x in resto[1:]:
            m = re.match(r"^(ILD|FNM|PGC)\d+$", x)
            if m: return V8_CANAL[m.group(1)]
        if resto[0] == "VDD" and "RMK" in resto[1:]: return "VENDA DIRETA REMARKETING"
        if resto[0] in V8_FUNIL: return V8_FUNIL[resto[0]]
    U = a.upper()
    for k, v in ACAO_PALAVRAS:
        if k in U: return v
    return None

def categoria_final(acao, origem):
    """(categoria, fonte, valor_sem_regra). Ação do contato; sem Ação, a origem do negócio (regra f da Sales Ops)."""
    c = acao_categoria(acao)
    if c is None:
        velha = RADAR_PARA_ACAO.get(origem_final(canal_de(acao)) or "")
        return (velha, "acao (regra antiga do Radar)", (acao or "").strip()) if velha else ("SEM CLASSIFICAÇÃO", "acao sem regra", (acao or "").strip())
    if c != SEM_INFO: return c, "acao", ""
    o = (origem or "").strip()
    if o:
        co = acao_categoria(o)
        if co and co != SEM_INFO: return co, "origem do negócio", ""
        if co is None:
            velha = RADAR_PARA_ACAO.get(origem_final(canal_de(o)) or "")
            if velha: return velha, "origem do negócio", ""
    return SEM_INFO, "", ""

def _dedup_salesops(rows):
    """Duplicado = mesmo telefone e e-mail, mesmos acao, origem e utm_content (preenchidos) e criação < 1 min: fica o mais recente."""
    P = lambda s_: dt.datetime.fromisoformat((s_ or "")[:19])
    def chave(r):
        ks = [(r.get("Contact.phone") or "").strip(), (r.get("Contact.email") or "").strip().lower(), (r.get("ContactFields.field_acao") or "").strip(),
              (r.get("DealFields.field_origem") or "").strip(), (r.get("DealFields.field_utm_content") or "").strip()]
        return tuple(ks) if all(ks) else None
    grupos = collections.defaultdict(list); fora = []
    for r in rows:
        k = chave(r)
        (grupos[k].append(r) if k else fora.append(r))
    manter = list(fora); dup = 0
    for k, g in grupos.items():
        g.sort(key=lambda r: r.get("Deal.createdAt") or "")
        for i, r in enumerate(g):
            if i + 1 < len(g) and (P(g[i + 1]["Deal.createdAt"]) - P(r["Deal.createdAt"])).total_seconds() < 60: dup += 1; continue
            manter.append(r)
    return manter, dup

def cmd_leadsdia(a):
    """Leads do dia pela régua da Sales Ops (um por negócio). --leads: negócios criados no dia nos funis de lead, com Stage.name,
    utm_content, Contact.email/name/phone (usados só para excluir e deduplicar; não são gravados); --busca/--chats: checagens extras
    do Radar para quem ficou SEM INFORMAÇÃO; --antigo: documentos anteriores do dia (para manter o tipo de tráfego já achado)."""
    dia = a.dia
    rows = []; vistos = set()
    for p in [x for x in a.leads.split(",") if x]:
        for r in rows_of(p):
            if r.get("Deal.id") in vistos: continue
            vistos.add(r.get("Deal.id")); rows.append(r)
    rows = [r for r in rows if r.get("Deal.originId") in FUNIS_LEAD and (r.get("Deal.createdAt") or "")[:10] == dia]
    exc = collections.Counter(); base = []
    for r in rows:
        em = (r.get("Contact.email") or "").lower(); nm = (r.get("Contact.name") or "").lower()
        if "@grupovirtus" in em: exc["email_grupovirtus"] += 1; continue
        if "teste" in em or "teste" in nm: exc["teste"] += 1; continue
        base.append(r)
    base, ndup = _dedup_salesops(base); exc["duplicados"] = ndup
    antigo = {}
    for p in [x for x in (getattr(a, "antigo", "") or "").split(",") if x]:
        try: d0 = json.load(open(p, encoding="utf-8"))
        except Exception: continue
        for l in d0.get("leads", []):
            if l.get("trafego"): antigo[(l["c"], l["produto"])] = l["trafego"]
    busca = collections.defaultdict(list)
    for p in [x for x in (getattr(a, "busca", "") or "").split(",") if x]:
        for r in rows_of(p): busca[r.get("Deal.contactId")].append(r)
    chl = collections.defaultdict(list)
    for p in [x for x in (getattr(a, "chats", "") or "").split(",") if x]:
        for r in rows_of(p):
            if r.get("Contact.id") and _lead_abriu(r.get("Chat.createdAt") or "", r.get("Chat.firstCustumerMessageAt") or ""):
                chl[r["Contact.id"]].append(r.get("Chat.firstCustumerMessageAt") or "")
    out = []; sem_regra = collections.Counter(); precisa = set()
    for r in sorted(base, key=lambda r: (r.get("Deal.createdAt") or "", r.get("Deal.id") or "")):
        cid = r.get("Deal.contactId") or ""; prod = FUNIS_LEAD[r["Deal.originId"]]
        acao = (r.get("ContactFields.field_acao") or "").strip(); orig = (r.get("DealFields.field_origem") or "").strip()
        utm = (r.get("DealFields.field_utm_campaign") or "").strip(); med = r.get("DealFields.field_utm_medium") or ""
        cat, fonte, sr = categoria_final(acao, orig)
        if sr: sem_regra[sr] += 1
        if cat == SEM_INFO:
            c2 = RADAR_PARA_ACAO.get(canal_utm(utm, med, r.get("DealFields.field_utm_source")) or ("Orgânico (redes do Wendell)" if _organico(utm, med) else ""))
            if c2: cat, fonte = c2, "UTM do negócio"
        if cat == SEM_INFO:
            achados = []
            for b in busca.get(cid, []):
                u = (b.get("DealFields.field_utm_campaign") or "").strip(); md = b.get("DealFields.field_utm_medium") or ""
                cn2 = canal_de((b.get("DealFields.field_origem") or "").strip(), u, md, b.get("DealFields.field_utm_source"), "")
                if cn2 in SEM_CANAL:
                    cp, cd = sck_info(b.get("DealFields.field_sck_completo"))
                    if cp: cn2 = canal_de("", cp, "paid", "", "")
                    elif cd: cn2 = canal_codigo(cd)[0] or cn2
                c3 = RADAR_PARA_ACAO.get(origem_final(cn2) or "")
                if c3: achados.append(((b.get("Deal.createdAt") or "")[:10] <= dia, b.get("Deal.createdAt") or "", c3))
            if achados: cat, fonte = sorted(achados)[-1][2], "outro negócio do contato"
        if cat == SEM_INFO:
            fm = [x for x in chl.get(cid, []) if x and x[:4] != "1970" and x[:10] <= dia]
            if fm: cat, fonte = "WHATSAPP", "1ª conversa no WhatsApp"
        if cat == SEM_INFO and orig and _norm(orig) not in ("SEM INFORMACAO",):
            cat, fonte = orig.upper(), "origem do negócio (valor)"  # regra f da Sales Ops: sem nada, vale o valor do campo origem
        if cat == SEM_INFO or fonte == "origem do negócio (valor)": precisa.add(cid)
        cn_velho, _, _ = canal_lead(acao_valida(acao), orig, utm, med, r.get("DealFields.field_utm_source"), r.get("Deal.sourceLabel"))
        traf = antigo.get((_hash(cid), prod)) or trafego_de(cn_velho, utm, med)
        st = (r.get("Stage.name") or "").strip()
        lev = (r["Deal.originId"] == FUNIL_CONEXAO_PRO) if prod == "Protagon" else (st in ETAPAS_LEV_ISD)
        item = {"d": hashlib.sha1(("d" + (r.get("Deal.id") or "")).encode()).hexdigest()[:10], "c": _hash(cid), "produto": prod,
                "acao": acao[:80] or orig[:80], "canal": cat, "fonte_canal": fonte, "trafego": traf, "lev": lev, "etapa": st[:40]}
        if prod == "Protagon": item["funil"] = "Conexão" if r["Deal.originId"] == FUNIL_CONEXAO_PRO else "Pré checkout"
        out.append(item)
    if getattr(a, "precisa", ""): json.dump(sorted(x for x in precisa if x), open(a.precisa, "w"))
    doc = {"dia": dia, "metodo": "origens_v3_salesops", "leads": out, "vendas": [], "excluidos": dict(exc), "sem_regra": dict(sem_regra)}
    json.dump(doc, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({"dia": dia, "negocios": len(rows), "leads": len(out), "excluidos": dict(exc), "levantadas": sum(1 for x in out if x["lev"]),
                      "por_canal": collections.Counter(x["canal"] for x in out).most_common(), "sem_regra": dict(sem_regra),
                      "precisa_busca": len(precisa)}, ensure_ascii=False))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("lotes"); [p.add_argument(x, required=True) for x in ("--origins", "--q1", "--q2", "--q3", "--dia", "--out")]; p.add_argument("--template")
    p = sp.add_parser("merge"); [p.add_argument(x, required=True) for x in ("--reads", "--dia", "--lotes", "--out")]
    p = sp.add_parser("maos"); [p.add_argument(x, required=True) for x in ("--q4", "--q6", "--q7", "--corte", "--out")]; p.add_argument("--dias", default=""); p.add_argument("--ia", default=""); p.add_argument("--verif", default="")
    p = sp.add_parser("conferir"); [p.add_argument(x, required=True) for x in ("--maos", "--out")]; p.add_argument("--verif", default=""); p.add_argument("--max", default="400")
    p = sp.add_parser("universo"); [p.add_argument(x, required=True) for x in ("--origins", "--q3", "--chats", "--dia", "--out")]; p.add_argument("--tam", default="40")
    p = sp.add_parser("maos2"); [p.add_argument(x, required=True) for x in ("--res", "--q6", "--donos", "--dia", "--corte", "--out")]
    p = sp.add_parser("classdoc"); [p.add_argument(x, required=True) for x in ("--res", "--dia", "--out")]
    p = sp.add_parser("verifdoc"); [p.add_argument(x, required=True) for x in ("--res", "--out")]
    p = sp.add_parser("pendentes"); [p.add_argument(x, required=True) for x in ("--store", "--ate")]
    p = sp.add_parser("datasets"); [p.add_argument(x, required=True) for x in ("--store", "--out")]; p.add_argument("--desde", default="2026-10-23")
    p = sp.add_parser("revisar"); [p.add_argument(x, required=True) for x in ("--maos", "--aud", "--out")]
    p = sp.add_parser("origensdia"); [p.add_argument(x, required=True) for x in ("--leads", "--vendas", "--hist", "--dia", "--out")]; p.add_argument("--busca", default=""); p.add_argument("--precisa", default=""); p.add_argument("--resta", default=""); p.add_argument("--chats", default=""); p.add_argument("--semcanal", default=""); p.add_argument("--auditoria", default="")
    p = sp.add_parser("leadsdia"); [p.add_argument(x, required=True) for x in ("--leads", "--dia", "--out")]; p.add_argument("--busca", default=""); p.add_argument("--chats", default=""); p.add_argument("--antigo", default=""); p.add_argument("--precisa", default="")
    p = sp.add_parser("vendasplan"); [p.add_argument(x, required=True) for x in ("--csv", "--hp", "--hist", "--desde", "--ate", "--out")]; p.add_argument("--chats", default="")
    p = sp.add_parser("reconf"); [p.add_argument(x, required=True) for x in ("--store", "--msgs", "--agora", "--desde", "--out")]; p.add_argument("--excl", default=""); p.add_argument("--ate", default="")
    p = sp.add_parser("levdoc"); [p.add_argument(x, required=True) for x in ("--q", "--dia", "--out")]
    p = sp.add_parser("contatos"); [p.add_argument(x, required=True) for x in ("--q", "--classe", "--dia", "--out")]
    a = ap.parse_args()
    {"lotes": cmd_lotes, "merge": cmd_merge, "datasets": cmd_datasets, "pendentes": cmd_pendentes, "maos": cmd_maos, "conferir": cmd_conferir, "universo": cmd_universo, "classdoc": cmd_classdoc, "contatos": cmd_contatos, "revisar": cmd_revisar, "maos2": cmd_maos2, "verifdoc": cmd_verifdoc, "origensdia": cmd_origensdia, "vendasplan": cmd_vendasplan, "reconf": cmd_reconf, "levdoc": cmd_levdoc, "leadsdia": cmd_leadsdia}[a.cmd](a)
