# Conferir levantadas de mão (Radar de Conversas Virtus)

Entrada: {ENTRADA} — lista JSON de casos {id, contato, dia, hora}. "hora" é a hora local (America/Sao_Paulo) em que o lead entrou em Conexão no dia "dia".
Saída: {SAIDA} — uma linha JSON por caso. Se o arquivo já existir, pule os ids que já estão nele.
SOMENTE LEITURA: nunca envie mensagem nem altere nada no Clint. Nunca grave nome, telefone ou e-mail (troque nome por [nome]).

1. Ferramentas: ToolSearch "select:mcp__Clint__execute_indicator_query,mcp__Clint__get_chat_messages".
2. Chats: uma consulta só com todos os contatos da entrada:
   execute_indicator_query {"measures":["Message.count"],"dimensions":["Contact.id","Chat.id"],"filters":[{"member":"Message.type","operator":"equals","values":["Cliente"]},{"member":"Contact.id","operator":"equals","values":[<contatos>]}],"timeDimensions":[{"dimension":"Message.createdAt","dateRange":["<menor dia>","<maior dia>"]}],"timezone":"America/Sao_Paulo","limit":5000}
   Se um contato tiver mais de um chat, use o que tem mais mensagens.
3. Para cada caso: get_chat_messages com chat_id COPIADO EXATAMENTE, limit 12, order DESC (várias chamadas em paralelo por vez). Horários da API são UTC (local = UTC-3). Olhe a(s) mensagem(ns) do lead (role CUSTOMER) de até 15 min antes da "hora" do caso e o que veio depois.
   - USER com content_object.sourceMetadata.automationName = automação ("agente de ia" no nome = agente de IA).
   - USER sem sourceMetadata = humano (ou IA via API; se vier em segundos depois de mensagem do agente de IA e no mesmo tom, conte como IA).
4. Linha de saída: {"id": "<id do caso>", "tipo": "quer_conversar" | "encerrar" | "auto_resposta" | "outro", "msg": "<texto do lead, até 80 caracteres>", "humano": true|false, "ia": true|false}
   - quer_conversar: botão ou texto de interesse ("Falar no whatsapp", "Eu quero", "Quero o link", "FALAR COM O TIME", pergunta, pedido de preço/link, "To aqui!" também conta).
   - encerrar: "Encerrar contato", "Não tenho interesse", "Desisti", "sair", "parar", pedir para não receber mais.
   - auto_resposta: mensagem automática do WhatsApp Business do próprio lead ("agradece seu contato", ausência).
   - outro: qualquer outra coisa (emoji solto, conversa sem relação).
   - humano: alguma mensagem humana depois da mensagem do lead (até agora). ia: o agente de IA conversou com o lead.
Ao terminar, responda em até 4 linhas: quantos casos, contagem por tipo, quantos com humano.
