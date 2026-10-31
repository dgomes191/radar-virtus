# Classificar a mensagem do lead no dia (Radar de Conversas Virtus)

Dia analisado: **{DIA}** (horário de Brasília). Os `created_at` da API vêm em UTC: Brasília = UTC − 3h.
Entrada: {ENTRADA} — lista JSON de contatos `{contact, produto: [..], chats: [..]}`.
Saída: {SAIDA} — uma linha JSON por contato (append, UTF-8). Se o arquivo já existir, pule os contatos que já estão nele. Grave cada linha assim que terminar o contato.
SOMENTE LEITURA: nunca envie mensagem nem altere nada no Clint. Nunca grave nome, apelido, telefone, e-mail, @ ou dado de saúde do lead (troque por [nome], [telefone]…).

## Passos
1. Ferramentas: ToolSearch "select:mcp__Clint__get_chat_messages".
2. Para cada contato, para cada chat da lista (copie o id EXATAMENTE): get_chat_messages(chat_id, limit=25, order="DESC"). Faça várias chamadas em paralelo.
3. Pegue as mensagens do lead (role CUSTOMER) do dia {DIA} em Brasília, em ordem cronológica.
4. Classifique e escreva a linha.

## Como classificar (vale a PRIMEIRA mensagem do lead no dia que se encaixar em "quer_conversar"; se nenhuma se encaixar, classifique pela primeira mensagem do dia)
- **quer_conversar**: o lead espera uma resposta do time ou mostra que quer comprar/falar. Exemplos: "Falar no whatsapp", "Falar com o time", "Eu quero", "Quero o link", "Quero minha condição", "QUERO SABER MAIS", "Valores", "Quanto custa?", qualquer pergunta, pedido de link/preço/parcelamento, "Quero participar", resposta a uma pergunta do vendedor numa negociação em andamento ("sim, pode ser à vista", "qual a data?").
- **automacao_atendeu**: clique ou resposta a um botão de template ("Quero participar", "QUERO PARTICIPAR", "Quero meu ingresso", "Prefiro por mensagem", "Pode confirmar"…) em que a automação ENTREGOU logo depois exatamente o que foi pedido (link da aula, link de compra/ingresso, a oferta) e o lead não escreveu mais nada pedindo algo. Se a automação só disse "vou te conectar com meu time" ou não respondeu, NÃO é este tipo: é quer_conversar.
- **nao_pedia**: mensagem que não espera resposta do time: recusa ou adiamento ("não tenho previsão, eu aviso", "agora não tenho tempo"), só confirmação de algo já combinado ("sim sim", "ok, pago na sexta"), reclamação ou xingamento sem pedido, resposta a negócio que o próprio lead já recusou. Também é nao_pedia a resposta a uma pergunta de qualificação da automação ("Qual sua experiência?" → "Primeira experiência"; "Quão importante é?" → "É uma prioridade"; "Já está faturando?" → "Não está, mas vai ficar!"; "Trabalhando", "Por indicação", "Tenho", "Posso") quando o lead não pede nada além da resposta.
- **suporte**: quem já é aluno/comprador ou ganhou ingresso pedindo suporte, não compra: acesso à plataforma, "faço parte do Vitalício", não consegue postar/acessar, QR code ou acesso ao evento, ingresso cortesia ("ganhei um ingresso", "posso levar acompanhante no ingresso que ganhei").
- **reengajou**: clique ou resposta de reengajamento que não pede nada: "To aqui!", "Sim, fui eu!", "Sim, vou acompanhar", "Vou estar lá", "ACESSAR INFORMAÇÕES" de convite de aula, "Tudo beleza", emoji/curtida, "ok", "obrigado".
- **saiu**: "Encerrar contato", "Não tenho interesse", "Desisti", "Sair", "Parar", pedido para não receber mais, "já comprei com outro".
- **auto_resposta**: mensagem automática do WhatsApp Business do próprio lead ("agradece seu contato", "no momento não posso atender").
- **outro**: nada acima (mensagem fora do assunto, engano de número).
Se o lead clicou "Falar no whatsapp" e segundos depois "Encerrar contato", vale **saiu**.

## Linha de saída
{"contact": "<id>", "produto": "ISD"|"Protagon", "tipo": "quer_conversar"|"automacao_atendeu"|"nao_pedia"|"suporte"|"reengajou"|"saiu"|"auto_resposta"|"outro", "hora": "HH:MM", "msg": "<texto do lead, até 80 caracteres; vários cliques seguidos separados por ' | '>", "ia": true|false}
- produto: um dos da lista de entrada; se a lista tiver os dois, o produto de que a conversa trata.
- hora: hora em Brasília da mensagem escolhida.
- ia: true se o "agente de ia" (automação com "agente de ia" no nome, ou resposta USER sem sourceMetadata segundos depois do agente) conversou com o lead depois dessa mensagem.
- Se não achar mensagem do lead no dia {DIA}, escreva tipo "outro", hora "", msg "sem mensagem no dia".

Ao terminar, responda em até 3 linhas: contatos feitos e contagem por tipo.

Leia SEMPRE o que o time/automação mandou antes e logo depois da mensagem do lead: o mesmo texto ("Quero participar", "Sim", "Tenho") pode ser pedido real ou só clique já atendido.
