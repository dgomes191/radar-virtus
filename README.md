# Radar de Conversas Virtus

Painel do time de receitas do Grupo Virtus (ISD e Protagon): atendimento no WhatsApp, funil de levantada de mão, leads e vendas por origem, objeções e frases das conversas.

- Painel publicado: https://claude.ai/artifact/Mset1HmQEwZHUecc67nSVd (tipo Dashboard)
- Atualização: rotina agendada todo dia às 7h (America/Sao_Paulo), com os dados até o dia anterior.

## O que tem aqui

| Pasta | O que é | Onde roda |
|---|---|---|
| `painel/index.html` | A página do painel (cálculos `dash.calc` + desenho) | Banco do painel: `files/index.html` |
| `script/radar.py` | Processa as consultas da Clint e a planilha de vendas e gera os datasets | Pacote de código (arquivo do painel) apontado por `radar_config/estado.codigo` |
| `script/estado.py` | Empacota e desempacota o estado da rotina (conversas lidas, quem quis conversar, origens…) como arquivos do painel | Mesmo pacote de código |
| `rotina/rotina.md` | Instruções passo a passo da rotina das 7h | Banco do painel: `radar_config/rotina` |
| `rotina/prompts/*.md` | Instruções dos subagentes (leitura das mensagens, 2ª leitura, auditoria das conversas) | Mesmo pacote de código |

**O que NÃO entra no repositório:** dados. Datasets, conversas, contatos (nome e e-mail de leads), vendas e qualquer arquivo exportado da Clint ou da planilha ficam só no banco do painel. Nunca suba telefone, e-mail, nome de lead ou dado de saúde. O `.gitignore` bloqueia `*.json`, `*.csv` e `*.xlsx` por isso.

## Como uma mudança chega ao painel

O painel e a rotina leem o código do **banco do painel**, não do GitHub. Fluxo combinado:

1. Faça a mudança numa branch e abra um pull request.
2. A outra pessoa revisa; depois do merge, peça ao Claude: "publica a versão do GitHub no Radar".
3. O Claude atualiza `files/index.html`, a rotina (`radar_config/rotina`) e o pacote de código (novo arquivo do painel + `radar_config/estado.codigo`) a partir da `main` e confere a página.

Desde 04/11/2026 a rotina não copia mais o banco (a ferramenta passou a recusar): o estado fica em arquivos do painel e o banco guarda só o ponteiro `radar_config/estado`.

## Regras de negócio (decididas pelo Diego)

**Fontes**
- Clint é **somente leitura**: nunca enviar mensagem nem alterar nada.
- Vendas e faturamento: planilha "Backup vendas" do comercial (só o time comercial, nunca o total da empresa). ISD = IMERSÃO, Protagon = PROTAGON; Coliseu e 5 Liberdades ficam fora.
- A venda é ligada ao comprador na Clint pelo código da transação (HP…).

**Funil do atendimento**
- *Leads totais*: leads que entraram no Clint no período, um por pessoa e produto (o mesmo número do bloco de origens).
- *Levantada de mão* (régua da Sales Ops, adotada em 31/10/2026): lead criado no período cujo negócio está **hoje** em Conexão ou etapa posterior, qualquer status. ISD: Conexão, Negociação, Follow automático, Stand by, Fechado. Protagon (pré-checkout): Conexão em diante. Protagon sessão aberta (395e2051): só Negociação, Follow up, Standby, Compra fechada (todo negócio nasce em "Conexão (sessão aberta)").
- *Pedidos de atendimento*, *respondidas em até 15 min* e *sem resposta*: leitura das mensagens do WhatsApp (desde 23/10/2026). Espera em horário útil (seg a sáb, 8h–20h). "Sem resposta" é reconferido todo dia nos últimos 10 dias (vendedor que responde depois sai do "sem resposta"). Respostas a perguntas da automação ("Primeira experiência", "É uma prioridade"…) não contam como pedido; pedidos de suporte de aluno ou de quem ganhou ingresso também não.

**Origens (11 + não identificada)**
Formulário nativo, WhatsApp (chamou direto), Orgânico, Meteórico, Webinário, Inlead (geração de demanda), Inlead (venda direta), Venda direta (página de vendas), Página comercial, Indicação, Remarketing. O que não se encaixa vira "Origem não identificada". Disparo não é origem.
Ordem de checagem: (1) campo Ação do contato; (2) Origem e utm_campaign do próprio negócio; (3) UTM/campanha/rastreio (sck) de qualquer outro negócio do contato; (4) conversa no WhatsApp aberta pelo próprio contato (1ª mensagem dele até 5 min da abertura). Tags não entram.

**Layout**: verde e dourado da Virtus.

## Histórico
O registro detalhado das decisões fica no documento do projeto "Virtus" no Claude (`claude/radar-conversas-handoff.md`).
