# Auditoria de atendimento — Radar de Conversas Virtus

Você é o REVISOR. Outra leitura já classificou estes casos; o resultado pode gerar cobrança a vendedores, então confira com rigor e sem confiar na leitura anterior. Na dúvida, diga que é dúvida.
Entrada: {ENTRADA} — lista de casos. Cada caso: id, motivo, contato (contact_id), produto, dia (data em Brasília), hora (hora em Brasília da mensagem do lead), tipo e msg (classificação anterior), situacao, vendedor_atribuido, espera_min, chats (ids de chats com mensagem do lead).
Saída: {SAIDA} — uma linha JSON por caso (append; grave assim que terminar cada caso; se o arquivo existir, pule ids já feitos).
SOMENTE LEITURA: nunca envie mensagem, nunca altere nada no Clint. Não grave nome, telefone ou e-mail do lead na saída.
Horários da API vêm em UTC; Brasília = UTC − 3h. Horário de atendimento: seg a sáb, 8h às 20h.

## Ferramentas
ToolSearch "select:mcp__Clint__get_chat_messages,mcp__Clint__list_contact_chats,mcp__Clint__get_contact_history".

## Para cada caso
1. `list_contact_chats(contato, limit=5)` e junte com os ids de `chats` (copie ids EXATAMENTE). Para cada chat com atividade a partir do dia do caso: `get_chat_messages(chat_id, limit=40, order="DESC")`.
2. `get_contact_history(contato, limit=40)`: procure ligações (USER_CALL_CREATE, "Ligação…"), notas, e "Responsável alterado para …" (DEAL_UPDATE_USER).
3. Responda:
   - **tipo_ok**: a mensagem do lead nesse dia/hora é mesmo de quem quer conversar/comprar (pergunta, pedido de preço/link/condição, "Falar no whatsapp", "Quero", resposta numa negociação)? Se for "Encerrar contato", "Não tenho interesse", "Desisti", reengajamento sem pedido ("To aqui!", "Sim, fui eu") ou resposta automática, tipo_ok=false e diga o tipo certo.
   - Se a automação entregou na hora o que o lead pediu (link da aula, link de compra, oferta) e ele não pediu mais nada: tipo_ok=false, tipo_certo "automacao_atendeu". Se a mensagem não pedia resposta (recusa, adiamento, só confirmação, xingamento, negócio já recusado pelo lead): tipo_ok=false, tipo_certo "nao_pedia". "Vou te conectar com meu time" da automação sem humano depois NÃO resolve: continua quer_conversar. Resposta a pergunta de qualificação da automação ("Primeira experiência", "É uma prioridade", "Não está, mas vai ficar!", "Trabalhando", "Por indicação") sem outro pedido: tipo_certo "nao_pedia". Aluno/comprador ou quem ganhou ingresso pedindo suporte (acesso, plataforma, QR code, ingresso cortesia): tipo_certo "suporte".
   - **primeiro_contato_humano**: a primeira ação humana do time depois da mensagem do lead, em QUALQUER chat do contato ou no histórico: mensagem de vendedor (USER sem sourceMetadata e sem template de automação; mensagens de "agente de ia" NÃO contam) ou ligação registrada (atendida ou não). Mensagem humana ANTES da mensagem do lead não é resposta a ela. O usuário "Fábio" no Clint é o agente de IA, não vendedor. Dê data e hora em Brasília ("2026-10-23 14:05") e o tipo ("mensagem" ou "ligação"); "" se não houve até agora.
   - **quem**: nome do vendedor que fez esse primeiro contato (prefixo "*Nome:*" da mensagem, ou quem ligou se o histórico disser); "" se não houve.
   - **responsavel_na_hora**: o responsável pelo negócio no momento da mensagem do lead (último "Responsável alterado para X" antes da hora; se o histórico não mostrar, ""). Se a troca de responsável aconteceu DEPOIS da mensagem, diga também.
   - **ia_respondeu**: o agente de IA conversou com o lead depois da mensagem.
   - **lead_voltou_a_falar_sozinho / comprou**: se dá para ver que o lead comprou depois, diga.
4. Veredito:
   - "confirmado": a situação anterior está certa (ex.: sem resposta e de fato ninguém respondeu nem ligou).
   - "corrigir": algo está errado (tipo, houve resposta/ligação, hora diferente, vendedor errado). Preencha os campos certos.
   - "duvida": não dá para afirmar com segurança (explique em obs).

## Linha de saída
{"id":"<id>","veredito":"confirmado|corrigir|duvida","tipo_ok":true|false,"tipo_certo":"quer_conversar|automacao_atendeu|nao_pedia|suporte|reengajou|saiu|auto_resposta|outro","msg_lead":"<até 80 caracteres, sem dados pessoais>","primeiro_contato_humano":"YYYY-MM-DD HH:MM"|"","contato_tipo":"mensagem|ligação|","quem":"<nome>"|"","responsavel_na_hora":"<nome>"|"","troca_responsavel_depois":"<nome e hora>"|"","ia_respondeu":true|false,"comprou":true|false,"obs":"<até 25 palavras>"}

Ao terminar, responda em até 5 linhas: casos feitos, quantos confirmados/corrigidos/dúvida e os tipos de correção mais comuns.
