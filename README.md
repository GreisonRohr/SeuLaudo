# Laudai

> Repositório `SeuLaudo`: o produto passou a se chamar **Laudai**. Os nomes internos
> (pacote, variáveis `SEULAUDO_*`, chaves de armazenamento) foram mantidos para não quebrar
> instalações e dados existentes.

O paciente importa o laudo com o resultado dos exames (PDF do laboratório ou foto) e recebe
uma explicação em linguagem simples: o que cada exame mede, o que o resultado significa,
perguntas para levar ao médico, exames para conversar com ele e a evolução dos valores ao
longo do tempo.

> **Conteúdo educativo.** O Laudai não diagnostica, não prescreve e não substitui o médico.
> Veja [Segurança, LGPD e Anvisa](#segurança-lgpd-e-anvisa).

**Versão 1 (este repositório):** sistema web para testar com laudos reais.

## Como funciona

```
 PDF / foto / texto ──► Leitura ──► Conferência ──► Regras do sistema ──► Interpretação ──► Laudo explicado
                       (Claude ou   (o paciente     (classificação pela   (Claude, em        + evolução
                        regras)      corrige)        referência do laudo   linguagem simples)  (gráficos)
                                                     e valores críticos)
```

1. **Perfis.** Um perfil para cada pessoa (você, filhos, pais). Para criar um perfil, é preciso
   aceitar o termo de uso dos dados de saúde.
2. **Leitura** (`app/extratores/`)
   - `claude`: lê PDFs e fotos de celular, inclusive laudos de imagem (ultrassom, tomografia…),
     com saída estruturada (JSON Schema). Para cada analito, transcreve valor, unidade e
     referência e escolhe a faixa que se aplica ao paciente quando o laudo traz várias (por sexo,
     idade ou metas). Também marca os campos lidos com dúvida e avisa sobre problemas no documento.
   - `texto`: regras, sem IA, para TXT e PDFs digitais. Serve para testar sem chave de API.
3. **Conferência.** O documento fica ao lado da transcrição. O paciente corrige o que for preciso,
   e a interpretação usa exatamente o que foi conferido.
4. **Regras do sistema** (`app/valores.py`, `app/analitos.py`). Esta etapa não depende da IA:
   - lê números no formato brasileiro (`1.234,5`, `250.000`, `< 0,5`) e faixas como `70 a 99`,
     `Inferior a 190`, `Superior a 40` e `Até 5,0`;
   - classifica cada valor como dentro, acima ou abaixo da referência **impressa no próprio laudo**;
   - padroniza o nome do analito (`data/analitos.csv`), para que "Glicemia de jejum" de um
     laboratório e "Glicose" de outro entrem no mesmo histórico;
   - aplica os **valores críticos** (`data/valores_criticos.csv`), comparando unidades
     (`mEq/L` = `mmol/L`, `/mm³` = `/µL`, `mil/mm³` = `10³/µL`). Um valor crítico sempre gera o
     aviso para procurar atendimento.
5. **Interpretação** (`app/interpretacao.py`). O Claude recebe o laudo conferido, **sem o nome do
   paciente**, junto com os valores anteriores do mesmo exame. Ele devolve:
   - um resumo do laudo;
   - para cada resultado, o que o exame mede, o que o valor significa e as causas comuns de
     alteração, inclusive as que não são doença;
   - perguntas para levar ao médico;
   - exames para conversar com o médico, apresentados como sugestão e não como pedido;
   - hábitos que costumam ajudar e orientação de acompanhamento;
   - sinais que pedem atendimento rápido.

   Sem chave de API, o sistema faz uma interpretação básica com as descrições do catálogo.
6. **Evolução.** Mostra um gráfico por exame com a faixa de referência sombreada, os pontos fora
   da faixa destacados e a tabela de valores. Só entram no mesmo gráfico valores com a mesma unidade.
7. **Exportar.** O botão "Imprimir / salvar PDF" gera um relatório para levar à consulta.

## Rodando

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...      # leitura de PDF/foto e interpretação completa
uvicorn app.main:app --reload --port 8000
```

Acesse http://localhost:8000. Para testar sem chave de API, cole o conteúdo de
`exemplos/laudo_exemplo.txt` e use a leitura "Regras (sem IA)" e a "Interpretação básica".

Testes: `pytest`. Os testes não acessam a rede, porque as chamadas ao Claude são simuladas.

### Prévia no claude.ai (sem servidor)

`preview/index.html` é uma versão de página única para testar no claude.ai, onde a leitura e a
explicação usam o Claude da conta de quem abre a página. As regras de classificação e de valores
críticos, o catálogo de analitos e os prompts são os mesmos do backend. O `preview/build.py`
gera a página a partir de `preview/template.html`. Na prévia, os laudos ficam guardados só no
navegador, e a imagem do documento não é guardada depois que a página é fechada.

```bash
python preview/build.py   # depois de mudar o template, os prompts ou os CSVs
```

### Publicar (Render, plano gratuito)

O processo é o mesmo do CheckExame. O `Dockerfile` e o `render.yaml` já estão prontos.
1. Crie o serviço no Render a partir deste repositório.
2. Em *Environment*, defina `ANTHROPIC_API_KEY` e `SEULAUDO_SENHA` (o usuário é `seulaudo`).

No plano gratuito os dados são apagados a cada nova publicação. Para guardar dados de verdade,
use um disco persistente (veja os próximos passos).

### Configuração (variáveis de ambiente, veja `.env.example`)

| Variável | Padrão | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chave da API da Anthropic |
| `SEULAUDO_CLAUDE_MODEL` | `claude-opus-5-5` | Modelo usado na leitura e na interpretação |
| `SEULAUDO_EFFORT_LEITURA` | `high` | Esforço na leitura (`low`…`max`). Fotos difíceis pedem `high` |
| `SEULAUDO_EFFORT_INTERPRETACAO` | `high` | Esforço na interpretação |
| `SEULAUDO_DADOS` | `./dados` | Banco SQLite e laudos enviados (fora do Git) |
| `SEULAUDO_SENHA` / `SEULAUDO_USUARIO` | — / `seulaudo` | Senha de acesso ao site (HTTP Basic) |

As chamadas ao Claude usam o *fallback* do servidor (`fallbacks: "default"`): se o modelo
recusar um documento por política, a API repete a chamada em outro modelo. Se a recusa
persistir, o paciente vê uma mensagem de erro amigável.

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/status` | Claude disponível e extratores |
| `GET` `POST` | `/api/perfis` | Lista e cria perfis (`consentimento: true` é obrigatório) |
| `DELETE` | `/api/perfis/{id}` | Exclui o perfil com todos os laudos, arquivos e histórico |
| `POST` | `/api/laudos` | Envia o laudo (`perfil_id`, `extrator`, `arquivo` ou `texto`) |
| `GET` | `/api/perfis/{id}/laudos` | Laudos do perfil |
| `GET` `PUT` `DELETE` | `/api/laudos/{id}` | Consulta, salva a conferência ou exclui o laudo |
| `POST` | `/api/laudos/{id}/interpretar` | Interpreta o laudo (`?basico=true` usa a versão sem IA) |
| `GET` | `/api/perfis/{id}/historico` | Resultados agrupados por analito, em ordem de data |

## Segurança, LGPD e Anvisa

- **Papel educativo.** O texto do sistema e o prompt proíbem diagnóstico, indicação de
  medicamentos ou doses e mudanças de tratamento. Exames complementares aparecem como "para
  conversar com o médico". O aviso aparece em todas as telas e no relatório.
- **A classificação e os valores críticos não dependem da IA.** São regras determinísticas
  baseadas na referência do próprio laudo. A IA não pode contradizer essa classificação.
- **Software como Dispositivo Médico (RDC Anvisa 657/2022).** Um software que interpreta
  resultados para o paciente pode ser enquadrado como dispositivo médico. Antes de abrir para o
  público, avalie o enquadramento com um especialista regulatório e mantenha o posicionamento
  educativo.
- **LGPD.** Dados de saúde são dados pessoais sensíveis. Esta versão já inclui:
  - consentimento explícito por perfil, com data e hora registradas;
  - exclusão do laudo ou do perfil inteiro;
  - envio do laudo para interpretação sem o nome do paciente;
  - laudos e banco fora do Git.

  Ainda faltam para produção: login individual (hoje é uma senha única para o site),
  criptografia em repouso, política de privacidade, registro de acesso, encarregado de dados
  (DPO) e contrato com o provedor de IA.
- **Revisão clínica.** Antes do uso público, é importante que um médico ou patologista clínico
  revise `data/analitos.csv`, `data/valores_criticos.csv` e o prompt de interpretação.

## Próximos passos sugeridos

1. Contas com login (e-mail + senha ou Google), em vez da senha única.
2. Banco persistente (PostgreSQL) e armazenamento de arquivos criptografado.
3. Revisão médica do catálogo de analitos, dos valores críticos e do prompt, com casos de teste
   (conjunto de laudos reais anonimizados com interpretação esperada).
4. Faixas de referência por idade e sexo no catálogo, para laudos que não trazem referência.
5. Lembretes de exames de controle e compartilhamento do relatório com o médico.
6. Integração com o CheckExame: o laboratório entrega o laudo direto no Laudai do paciente.
