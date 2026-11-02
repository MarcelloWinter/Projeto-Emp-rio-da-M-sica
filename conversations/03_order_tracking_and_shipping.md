# Example 3 — Order tracking with failed then successful identity check + shipping policy

_Exported 2026-03-23 10:30 (store time)._

**Mel:** Oi! Eu sou a Mel, assistente virtual da Empório da Música 🎸 Como posso te ajudar hoje?

**Customer:** Quero saber onde está meu pedido 8

**Mel:** Para consultar o status do seu pedido 8, preciso que você me informe o e-mail ou telefone cadastrado no pedido para confirmar sua identidade. Pode me passar, por favor?

**Customer:** acho que usei ana.carolina@gmail.com

<details><summary>Tools called</summary>

- `get_order_status({"order_id": 8, "email_or_phone": "ana.carolina@gmail.com"})`

</details>

**Mel:** Não consegui confirmar o pedido com o número 8 e o e-mail ana.carolina@gmail.com. Pode verificar se os dados estão corretos ou me passar outro e-mail ou telefone cadastrado?

**Customer:** Desculpa, é anacarol.ferreira@coldmail.com

<details><summary>Tools called</summary>

- `get_order_status({"order_id": 8, "email_or_phone": "anacarol.ferreira@coldmail.com"})`

</details>

**Mel:** Ana, seu pedido 8 com o ukulele Kala KA-C Concert Mogno foi enviado. O código de rastreamento é BRJL5544332BR e a previsão de entrega era para 28/02/2026. Posso ajudar em mais alguma coisa?

**Customer:** E se eu morasse em Dourados, como seria o frete e o prazo?

<details><summary>Tools called</summary>

- `search_store_policies({"query": "frete Dourados"})`

</details>

**Mel:** Para Dourados, o frete é feito pelos Correios (PAC ou SEDEX) ou pela transportadora Jadlog. O prazo estimado é:

- PAC: 5 a 12 dias úteis
- SEDEX: 2 a 5 dias úteis
- Jadlog: 3 a 8 dias úteis

O valor do frete é calculado automaticamente pelo sistema com base no CEP, peso e dimensões do produto. Todos os envios têm seguro contra extravios e danos. Quer que eu ajude com mais alguma coisa?
