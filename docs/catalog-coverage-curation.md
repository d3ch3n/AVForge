# Catalog Coverage Curation

## Natureza e escopo

Este documento e normativo para o processo de curadoria de catalogo do
AVForge. Ele define quando uma equipe de curadoria pode declarar cobertura
fechada de protocolos em um equipment record.

Este documento nao e normativo para o JSON Schema, nao altera a semantica do
Compatibility Analyzer, nao introduz campos e nao substitui a documentacao
oficial do fabricante. O campo descrito aqui ja pertence ao schema v3.4:

```json
"catalog_coverage": {
  "communication_protocols": {
    "complete": true
  }
}
```

As decisoes de modelo e a semantica geral estao em
[`docs/data-model.md`](data-model.md). O comportamento do Analyzer esta em
[`docs/compatibility-analyzer-contract.md`](compatibility-analyzer-contract.md).

## Definicao de coverage

`communication_protocols.complete=true` significa que todas as protocol
families oficialmente documentadas para o fabricante, modelo exato, variante
e escopo catalogados, dentro do dominio de interoperabilidade funcional
suportado pelo Compatibility Analyzer, foram registradas.

A declaracao nao significa que foram catalogados:

- todos os protocolos existentes no equipamento;
- todos os transportes;
- todos os servicos de rede;
- todos os mecanismos de seguranca;
- todos os protocolos de gerenciamento;
- todos os detalhes de implementacao;
- todas as possiveis funcoes futuras de firmware;
- uma negacao universal de suporte fora do escopo documentado.

Coverage e uma afirmacao limitada ao record e ao dominio declarados. Ela nao
afirma suporte ou nao suporte permanente em outra variante, firmware, opcao,
licenca, modulo ou instancia.

## Open world e closed world

O catalogo opera em open-world por padrao:

```text
absence of evidence != evidence of absence
```

Sem `catalog_coverage`, com `communication_protocols` ausente ou com
`complete=false`, a ausencia de uma protocol family solicitada nao prova que o
equipamento nao a suporta. Quando a protocol layer for aplicavel e nao existir
evidencia especifica suficiente na propria analise de protocolo para determinar
incompatibilidade, o resultado da protocol layer e `INSUFFICIENT_DATA`. Na
analise de protocolo, evidencia especifica pode determinar `INCOMPATIBLE`
quando houver protocolo explicitamente contraditorio, capability do protocolo
com `availability: "unavailable"` ou capability do protocolo explicitamente
atribuida fora da interface selecionada. A precedencia e a agregacao continuam
sendo as definidas pelo contrato do Compatibility Analyzer.

Mesmo quando a protocol layer resulta em `INSUFFICIENT_DATA`, outras layers
independentes podem produzir `INCOMPATIBLE`, conforme sua aplicabilidade e
evidencia disponivel, incluindo `physical`, `electrical`, `signal`, `direction`,
`restrictions` e `capacity`. Nesse caso, o resultado final pode ser
`INCOMPATIBLE` pela regra de agregacao sem que a protocol layer deixe de ser
`INSUFFICIENT_DATA`.

Com `communication_protocols.complete=true`, a ausencia de uma protocol family
solicitada pode sustentar `INCOMPATIBLE` na protocol layer quando a solicitacao
contenha `requested_function.protocol_family`, a protocol layer seja aplicavel,
a familia pertenca ao dominio certificado e esteja ausente do
catalogo completo naquele dominio. Coverage nao determina sozinha o resultado
final: evidencia especifica continua sendo analisada normalmente, as demais
layers permanecem independentes e a agregacao final continua pertencendo ao
Compatibility Analyzer. Essa e uma evidencia negativa de catalogo, nao uma
afirmacao universal sobre o produto.

Quando a protocol family estiver explicitamente presente, coverage nao
substitui a analise normal de capability, assignment, direction, availability,
restrictions e capacity. Coverage tambem nao participa da decisao quando nao
ha `requested_function.protocol_family`.

## Escopo da certificacao

Cada certificacao deve identificar explicitamente:

- fabricante;
- modelo exato;
- variante exata, quando aplicavel;
- dominio funcional certificado;
- documentacao oficial revisada;
- versao de schema compativel.

Para o campo atual `catalog_coverage.communication_protocols.complete`, o
dominio certificado e o conjunto de protocol families pertencentes ao dominio
de interoperabilidade funcional atualmente suportado pelo Compatibility
Analyzer para o modelo e a variante auditados. A ausencia de uma familia so
pode ser interpretada como evidencia negativa dentro desse dominio
certificado. O dominio certificado e um metadado do processo de curadoria; nao
e um novo campo do Equipment Schema.

Coverage nao e transferida automaticamente entre:

- modelos da mesma familia;
- chassis e modulos;
- variantes com opcoes ou licencas diferentes;
- revisoes de hardware;
- firmwares com diferencas funcionais;
- produtos semelhantes.

Coverage pertence somente ao equipment record que a declara. Coverage de um
chassis nao certifica protocolos fornecidos por modulos. Coverage de um
modulo nao e herdada automaticamente pelo chassis. Cada record e certificado
no seu proprio escopo.

## Fontes aceitas

Para certificar `complete=true`, a base final deve ser formada por fontes
oficiais do fabricante, priorizadas nesta ordem:

1. Product page oficial.
2. Specification ou datasheet oficial.
3. Product manual ou user manual oficial.
4. Architecture and Engineering Specification oficial.
5. Help ou documentacao oficial.
6. Notas oficiais especificas de firmware, licenca ou opcao, quando necessarias.

Fontes nao oficiais podem auxiliar a investigacao, mas nao podem ser a base
final isolada para `complete=true`. Revendedores, foruns, Reddit, blogs,
videos de terceiros e paginas de integradores nao sao evidencia suficiente
isoladamente.

As fontes usadas devem ser listadas no record ou no registro editorial
correspondente, conforme a pratica do repositorio. A afirmacao de coverage nao
exige um novo campo de evidence dentro de `catalog_coverage`.

## Fluxo de curadoria

### Step 1 - Identify exact record

Confirmar `manufacturer`, `model`, variante, identidade do produto e
`schema_version`. Confirmar que o record nao esta sendo confundido com outro
modelo, modulo, chassis ou revisao.

### Step 2 - Enumerate official sources

Listar product page, datasheets, manuais, especificacoes A&E, help oficial e
documentos de firmware, licenca ou opcao usados na revisao. Registrar URLs,
titulos e idioma quando disponiveis.

### Step 3 - Inventory documented functions

Extrair das fontes todas as funcoes e tecnologias candidatas, incluindo
protocolos AV, ecossistemas de controle, audio ou video em rede, interfaces
USB, serial, servicos, sincronizacao, gerenciamento e dependencias. Nesta
etapa, ainda nao assumir que cada item e uma protocol family.

### Step 4 - Classify candidates

Classificar cada item conforme a taxonomia arquitetural abaixo. Registrar a
evidencia e a razao da classificacao.

### Step 5 - Identify true protocol families

Determinar quais itens sao protocol families reais dentro do dominio de
interoperabilidade funcional do Analyzer. A pergunta nao e quais protocolos o
equipamento usa internamente, mas quais presencas, ausencias, assignments,
direcoes ou configuracoes alteram diretamente a interoperabilidade funcional.

### Step 6 - Compare with record

Comparar cada protocol family documentada com `signals`,
`communication_capabilities`, `connection_constraints`, interfaces e demais
estruturas existentes. Verificar se a familia esta identificada pelo ID
canonico correto e no nivel correto.

### Step 7 - Resolve gaps

Resolver, antes da certificacao, cada `PROTOCOL_COVERAGE_GAP`,
`VOCABULARY_GAP` e `MODEL_GAP`. Separar esses bloqueios de detalhes
operacionais que nao impedem reconhecer a existencia da familia.

### Step 8 - Validate assignments

Auditar `direction`, `interface_assignment`, `capacity`, `availability` e
`restrictions`. Nao copiar automaticamente propriedades de outra capability
ou de outro modelo.

### Step 9 - Verify no true family is missing

Produzir uma lista explicita de protocol families oficialmente documentadas e
ausentes do record. Para certificar coverage, essa lista deve ser:

```text
NONE
```

### Step 10 - Set schema version

Se `catalog_coverage` for usado, o equipment record deve declarar uma
`schema_version` cuja estrutura efetivamente suporte `catalog_coverage`. O
campo foi introduzido no schema v3.4.0, mas uma versao futura nao e
automaticamente compativel: a compatibilidade deve ser verificada contra o
schema efetivamente usado.

### Step 11 - Add coverage

Adicionar somente o objeto de coverage definido pelo schema, sem campos
editoriais extras, depois que todos os bloqueios forem resolvidos.

### Step 12 - Controlled Analyzer tests

Executar testes positive, negative e open-world control. Os testes devem usar
requests e interfaces tecnicamente apropriados ao caso e devem verificar tanto
o resultado final quanto a protocol layer quando aplicavel.

### Step 13 - Full validation

Executar o conjunto de validacoes do repositorio e exigir que a suite esteja
integralmente verde. Os numeros atuais da suite podem mudar; eles nao sao uma
regra normativa permanente.

### Step 14 - Review before commit

Revisar fontes, matriz de familias, gaps, testes, diff e escopo antes de
publicar. A declaracao somente deve ser commitada apos essa revisao.

## Classificacao arquitetural

Usar as categorias abaixo para classificar cada candidato encontrado:

| Categoria | Significado |
| --- | --- |
| `AV_INTEROPERABILITY_PROTOCOL` | Protocolo/ecossistema cuja presenca altera diretamente a interoperabilidade AV. |
| `CONTROL_PROTOCOL` | Protocolo/ecossistema de controle funcional entre endpoints ou sistemas. |
| `MANAGEMENT_PROTOCOL` | Administracao, monitoramento, status, logging ou configuracao do equipamento. |
| `TRANSPORT_DEPENDENCY` | Transporte ou dependencia tecnica usada por outra funcao, sem ser a funcao interoperavel. |
| `NETWORK_SERVICE` | Servico de rede auxiliar, como descoberta, configuracao ou suporte operacional. |
| `SECURITY_MECHANISM` | Mecanismo de autenticacao, criptografia ou protecao de acesso. |
| `ADDRESSING_INFRASTRUCTURE` | Enderecamento e infraestrutura de configuracao de rede. |
| `PHYSICAL_OR_LINK_TECHNOLOGY` | Conector, meio fisico, camada de enlace ou interface eletrica. |
| `IMPLEMENTATION_DETAIL` | Detalhe interno sem papel independente na interoperabilidade catalogada. |

Normalmente, somente `AV_INTEROPERABILITY_PROTOCOL` e `CONTROL_PROTOCOL` sao
candidatos diretos a `protocol_family` no dominio atual. As demais categorias
nao devem ser transformadas automaticamente em protocol families.

## Pergunta de interoperabilidade

Para cada candidato, perguntar:

> Faz sentido um usuario solicitar isto como
> `requested_function.protocol_family = X` e esperar que a presenca ou
> ausencia de X altere diretamente a compatibilidade funcional entre os
> endpoints?

Se a resposta for sim, o item e um forte candidato a `protocol_family`. Se a
resposta for nao, ele provavelmente pertence a transporte, gerenciamento,
seguranca, networking, enderecamento ou detalhe de implementacao. A pergunta
nao substitui evidencia documental.

## Gaps

### `PROTOCOL_COVERAGE_GAP`

Uma verdadeira protocol family oficialmente documentada esta ausente do
record.

### `VOCABULARY_GAP`

A familia necessaria existe documentalmente, mas nao possui ID canonico no
vocabulary.

### `MODEL_GAP`

O modelo ou schema atual nao consegue representar uma caracteristica
necessaria para decidir corretamente a interoperabilidade.

### `CAPABILITY_DETAIL_GAP`

A familia existe e esta corretamente identificada, mas faltam detalhes
operacionais. O gap pode ser considerado nao bloqueante somente quando o
detalhe ausente nao altera materialmente a existencia da protocol family, a
applicability, o assignment relevante, a availability relevante, as
restrictions relevantes ou a conclusao sobre interoperabilidade dentro do
dominio certificado. Se puder alterar qualquer uma dessas conclusoes, deve
bloquear a certificacao ate ser resolvido ou reclassificado adequadamente.

### `INSUFFICIENT_DOCUMENTATION`

A documentacao oficial nao permite determinar de forma confiavel se uma
protocol family funcional existe ou como ela se aplica.

## Blockers

`complete=true` nao pode ser declarado quando houver:

- `PROTOCOL_COVERAGE_GAP`;
- `VOCABULARY_GAP` que impeca registrar uma familia verdadeira;
- `MODEL_GAP` que torne a presenca ou ausencia semanticamente incorreta;
- `INSUFFICIENT_DOCUMENTATION` sobre uma candidata funcional critica.

Um `CAPABILITY_DETAIL_GAP` isolado nao necessariamente bloqueia coverage.
Isso deve ser decidido caso a caso, documentando por que a existencia e a
interoperabilidade da familia continuam determinadas.

## Assignment e direction

O significado de `interface_assignment.mode` deve seguir o comportamento
documentado do produto:

- `fixed`: a capability esta vinculada as interfaces declaradas;
- `configurable`: a capability pode ser configurada em uma das interfaces permitidas;
- `simultaneous`: a capability pode operar simultaneamente nas interfaces declaradas;
- `redundant`: as interfaces declaradas sao caminhos redundantes;
- `segregated`: a capability pode ser distribuida conforme a segregacao declarada.

Uma interface default nao e automaticamente uma interface fixed ou exclusiva.
Uma selecao default continua configuravel quando a documentacao tambem declara
outras interfaces permitidas.

`direction` da interface e `direction` da capability podem ter niveis
distintos: uma interface bidirecional pode hospedar capabilities de entrada,
saida ou ambas. O assignment deve ser auditado na capability especifica, nao
inferido apenas do conector Ethernet.

## Licencas e modifiers

Coverage certifica a existencia documentada da protocol family. Ela nao
assume que toda capacidade opcional esta ativa em toda instancia.

Uma familia pode ser corretamente catalogada quando:

- depende de licenca;
- possui capacidade base e expandida;
- possui `capability_modifier`;
- possui `availability` condicional.

Nesses casos, o record deve manter a capacidade base e os modificadores
documentados. O Analyzer deve tratar assignment, availability e capacidade de
forma separada da existencia da protocol family.

## Testes obrigatorios

Antes de publicar `complete=true`, executar pelo menos estes casos:

### A. Positive present protocol

Solicitar uma protocol family existente. A analise deve seguir o caminho
normal de capability, assignment, direction, restrictions e capacity. Coverage
nao deve interferir indevidamente.

### B. Negative closed-world

Solicitar uma protocol family ausente. Com `complete=true`, a protocol layer
deve ser `INCOMPATIBLE` quando aplicavel, por ausencia no escopo oficial
completo.

### C. Open-world control

Criar um clone em memoria do mesmo record, remover somente
`catalog_coverage` e repetir a solicitacao ausente. O resultado esperado e
`INSUFFICIENT_DATA`.

### D. Request without protocol family

Executar uma request sem `requested_function.protocol_family`. Coverage nao
deve participar da decisao nem ativar a protocol layer.

### E. Existing conditional case

Solicitar uma familia existente com assignment configuravel, licenca ou outra
condicao documentada. O resultado deve continuar `CONDITIONALLY_COMPATIBLE`
quando a condicao for o unico bloqueio conhecido.

## Validacoes obrigatorias

Executar, conforme aplicavel ao diff:

- JSON parse;
- Draft 2020-12;
- Semantic Validator;
- Compatibility Analyzer;
- Schema tests;
- `compileall`;
- `git diff --check`.

A suite deve estar integralmente verde. Nao fixar a quantidade de testes como
regra normativa: novos testes podem ser adicionados e a suite pode evoluir.

## Exemplos de aplicacao

Os exemplos abaixo demonstram o processo. Eles nao criam regras especiais
para Crestron ou Q-SYS.

### Example A - Crestron DM-NVX-360C

Na revisao do modelo exato, as familias e funcoes relevantes incluem:

- DM NVX;
- AES67;
- USB 2.0 extension;
- CEC.

Dante foi explicitamente considerado nao aplicavel ao modelo exato. Depois de
resolver a matriz de familias e os detalhes necessarios, o record pode receber
`complete=true`.

Com a coverage presente, solicitar `dm-nvx` em uma interface Ethernet sem essa
familia no lado contrario produz `INCOMPATIBLE` na protocol layer. Um clone em
memoria sem `catalog_coverage`, submetido a mesma request, produz
`INSUFFICIENT_DATA`.

### Example B - Q-SYS Core 8 Flex

As familias funcionais documentadas e catalogadas incluem:

- Q-LAN;
- AES67;
- Dante;
- Q-SYS Control;
- SIP.

SIP foi inicialmente um gap porque a documentacao identificava SIP enquanto o
record usava somente a categoria generica VoIP. O gap foi resolvido antes de
adicionar coverage.

Com `complete=true`, `dm-nvx` ausente produz `INCOMPATIBLE` na protocol layer.
O clone do Core 8 Flex sem coverage produz `INSUFFICIENT_DATA`. Isso demonstra
closed-world e open-world sem acoplar a regra ao fabricante.

## Anti-patterns

Nao fazer o seguinte:

- marcar `complete=true` porque o record "parece completo";
- inferir protocolo pelo conector;
- inferir Dante porque existe Ethernet;
- inferir SIP porque existe VoIP generico;
- inventar `unsupported_protocols` sem fonte;
- criar capability `unavailable` somente para forcar incompatibilidade;
- usar `known_compatibility` como override de evidencia tecnica, restrictions,
  availability, assignment ou das layers do Analyzer;
- tratar HTTPS, SSH ou DHCP como protocolos AV automaticamente;
- considerar interface default como fixed;
- herdar coverage entre produtos;
- usar fonte de revendedor como unica evidencia;
- alterar o Analyzer para acomodar um fabricante especifico.

## Decision table

| Pergunta | Decisao |
| --- | --- |
| True protocol family missing? | YES -> DO NOT CERTIFY |
| Vocabulary gap blocking family? | YES -> DO NOT CERTIFY |
| Model gap affecting correctness? | YES -> DO NOT CERTIFY |
| Insufficient official evidence for critical family? | YES -> DO NOT CERTIFY |
| Only capability detail gaps? | MAY CERTIFY AFTER REVIEW |
| No blocking gaps? | ELIGIBLE FOR `complete=true` |

## Template de certificacao

```text
MODEL:
MANUFACTURER:
VARIANT:
CERTIFIED_SCOPE:
SCHEMA_VERSION:

OFFICIAL SOURCES:
[...]
Quando disponiveis, registrar titulo, tipo da fonte, URL ou referencia,
versao ou revisao e data relevante. Esses metadados melhoram a rastreabilidade
e nao sao todos obrigatorios quando a fonte nao os fornece.

TRUE PROTOCOL FAMILIES PRESENT:
[...]

TRUE PROTOCOL FAMILIES MISSING:
[...]

NON-COVERAGE DEPENDENCIES:
[...]

VOCABULARY GAPS:
[...]

MODEL GAPS:
[...]

CAPABILITY DETAIL GAPS:
[...]

BLOCKING GAPS:
[...]

CLOSED-WORLD TEST:
[...]

OPEN-WORLD CONTROL:
[...]

FULL VALIDATION:
- JSON parse: PASS / FAIL
- Draft validation: PASS / FAIL
- Semantic Validator: [resultado]
- Compatibility Analyzer: [resultado]
- Schema tests: [resultado]
- compileall: PASS / FAIL
- git diff --check: PASS / FAIL

CAN SET communication_protocols.complete=true:
YES / NO

CLASSIFICATION:
READY_FOR_COVERAGE
NEEDS_RECORD_COMPLETION
NEEDS_MODEL_REVISION
INSUFFICIENT_DOCUMENTATION
```

## Checklist final

Antes de publicar, confirmar:

- o record exato e o escopo foram identificados;
- todas as fontes oficiais relevantes foram listadas;
- candidatos foram classificados arquiteturalmente;
- toda verdadeira protocol family foi comparada ao record;
- a lista de familias verdadeiras ausentes e `NONE`;
- nao ha vocabulary gap ou model gap bloqueador;
- assignments, directions, capacities, availability e restrictions foram revisados;
- testes closed-world, open-world, positive, conditional e sem protocolo foram executados;
- validacoes completas passaram;
- o diff contem somente o escopo aprovado;
- a revisao editorial ocorreu antes do commit.
