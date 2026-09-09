# Decisões do Modelo de Dados

## Escopo

`equipment.schema.json` define um modelo universal de equipamento AV, em vez de um schema dedicado a um fabricante ou categoria. Campos específicos podem ser acomodados em `capabilities`, `extensions` e `custom_fields`, preservando um núcleo comum e IDs estáveis para relações futuras. O schema não contém campos específicos do Q-SYS.

## Catalog Coverage

`catalog_coverage` registra uma afirmação de completude de catálogo por domínio.
Na versão 3.7, o único domínio modelado é
`catalog_coverage.communication_protocols.complete`.

Quando `catalog_coverage` ou `communication_protocols` estão ausentes, ou
quando `complete` é `false`, a cobertura de protocolos permanece incompleta.
Um protocolo ausente nesse caso significa somente não documentado ou não
conhecido; não significa que o equipamento não o suporta.

Quando `complete` é `true`, a afirmação é que todas as capacidades e famílias
de protocolo oficialmente documentadas para o modelo, variante e escopo
catalogados foram registradas. Um protocolo ausente pode então ser interpretado
por uma camada de compatibilidade como ausente do catálogo oficial completo
daquele escopo. Isso não é prova universal de não suporte, nem afirma que o
produto nunca poderá receber suporte por firmware, licença ou opção futura.

Catalog coverage é independente de `equipment.status`. `status: "approved"`
não implica `communication_protocols.complete: true`; um record `draft` pode
estruturalmente possuir `complete: true`, embora essa afirmação dependa de
governança e revisão adequadas.

`complete: true` não exige campos estruturais de evidence. Como regra de
governança, a afirmação só deve ser usada após a revisão das fontes oficiais
relevantes para o modelo exato, como product manual, datasheet/spec sheet,
página oficial do produto e documentação oficial de features. Essas fontes
continuam na estrutura de documentação e no processo editorial, não dentro de
`catalog_coverage`.

Coverage pertence somente ao equipment record que a declara. A coverage de um
chassis, como `DMF-CI-8`, não cobre protocolos fornecidos por placas
`DM-NVX`, outros módulos ou módulos instalados em uma futura instância. Cada
módulo possui seu próprio record e sua própria coverage. Nenhuma regra de
composição é criada por este campo.

## Identidade e escopo dos IDs

O `id` do equipamento é obrigatório. Cada porta física conectável deve ter seu próprio `interfaces[].id`; `quantity` só expressa uma quantidade agregada de elementos equivalentes e nunca identifica portas individuais. Signals/capabilities, restrições, relações de compatibilidade e connection points também possuem IDs próprios. Esses IDs são estáveis no cadastro e não devem depender de labels visuais.

IDs usados em `functional_behavior` são referências a signals/capabilities ou entidades locais do mesmo equipamento. `interface_id` em `connection_points` e `poe_supplied` referencia uma interface local. `target_equipment_id` e `remote_interface_id` em relações apontam para entidades de outro cadastro quando esse cadastro existir. O formato do ID é validado, mas sua unicidade global e a existência do alvo não são garantidas pelo JSON Schema.

## Interfaces, conectores e pontos físicos

Uma `physical_connector` é o objeto físico real no painel/equipamento. Um `connection_point` é um pino, terminal, contato ou posição individual dentro desse conector. Uma `interface` é a função conectável usada pela engenharia. Portanto, interface e conector não são a mesma entidade.

`physical_connectors` é opcional. Um conector simples, como RJ45 ou USB, pode continuar descrito somente em `interfaces[].connector`. Quando um conector compartilhado tiver valor de engenharia, a interface pode declarar `physical_connection.connector_id` e um ou mais `connection_point_ids`. Várias interfaces podem referenciar pontos diferentes do mesmo conector físico; um ponto não deve ser duplicado em interfaces diferentes.

Exemplo simples: uma interface `lan-a` pode usar `connector: "RJ45"` sem detalhar seus contatos. Exemplo compartilhado: um borne físico `gpio-terminal-block` contém pontos `gpio-in-1`, `gpio-in-2`, `common` e `+12v`, enquanto interfaces funcionais separadas referenciam os pontos que utilizam. Uma interface RS-232 pode referenciar `tx`, `rx` e `ground` do seu conector.

Uma interface continua possuindo `connector` e uma lista independente de `signals`. Essa separação é necessária porque o mesmo conector pode transportar tecnologias incompatíveis. Uma interface RJ45, por exemplo, pode representar LAN, HDBaseT ou um protocolo proprietário.

`signal_type` é uma categoria ampla, como `audio`, `video`, `network`, `control` ou `data`. `signal_family` identifica uma família técnica, como `analog-audio`, `AES3`, `Ethernet` ou `HDBaseT`; `signal_format` descreve um formato quando aplicável; `protocol_family` identifica o protocolo ou ecossistema específico. `connector` não deve receber valores de sinal ou protocolo.

### Physical Connection Model v1

O Schema 3.7 adiciona `interface.physical_connection_capabilities` como a
localização canônica das capabilities físicas da interface. O primeiro campo
é `passive_interconnection.status`:

- `supported` significa que a interface pode participar de uma interligação
  passiva funcional que preserva a função do endpoint, sujeita às demais
  camadas de compatibilidade.
- `unsupported` significa que há evidência explícita de que a interface não
  suporta essa forma de interligação.
- A ausência de `physical_connection_capabilities` ou de
  `passive_interconnection` significa `UNKNOWN`; não existe default para
  `unsupported`.

Essa capability não declara mating direto, igualdade de connectors, pinout,
contact mapping, channel mapping, polaridade, shield, referência, cabo
específico ou compatibilidade completa de signal, direction, electrical ou
protocol. `DIRECT` continua dependendo da identidade e das regras de mating
do connector. A capability é destinada à futura análise de
`APPROPRIATE_MEDIUM`; o Analyzer atual ainda não a consome.

Interligações ativas, como conversores, transformers, DSPs e bridges, estão
fora do Physical Connection Model v1.

Características físicas e elétricas da porta pertencem a `electrical_characteristics` da interface. Características do sinal, formato ou variante pertencem a `signal_characteristics` e aos campos da capability. O schema mantém esses objetos extensíveis, mas não define ainda um vocabulário completo para impedância, nível, largura de banda ou resolução.

`interface.direction` descreve a direção geral da porta. Uma capability pode declarar outra `direction`, permitindo que uma interface bidirecional tenha capacidades de entrada e saída diferentes.

### Características elétricas

`interface.electrical_characteristics` é a estrutura canônica para
características elétricas da porta. Ela é opcional e possui perfis também
opcionais `input` e `output`. `signal_characteristics` continua reservado
para características do sinal, formato, variante ou protocolo; dados
elétricos existentes nesse objeto são legados e não constituem a nova forma
canônica.

Na análise conceitual de uma conexão, o papel `SOURCE` usa o perfil `output`
e o papel `TARGET` usa o perfil `input`. A seleção do signal e a resolução do
perfil elétrico são decisões separadas. A v1 não associa um perfil elétrico
diretamente a signal IDs.

Os perfis podem declarar `balance_modes` com `balanced`, `unbalanced` ou ambos,
e `operating_level_classes` com `mic`, `line` ou ambos. `nominal_levels` é uma
lista de medições; `maximum_level` representa o limite do papel; e
`impedance.nominal` representa a impedância nominal. Somente o perfil `output`
pode declarar `minimum_load_impedance`.

Valores de medição são armazenados como `value` e `unit`, sem conversão ou
campo textual paralelo. O schema não converte dBu, dBV ou Vrms. A integridade
do `unit` em relação ao vocabulário é responsabilidade da validação semântica.
Valores negativos são válidos para níveis em dB, mas não para impedância,
tensão ou corrente quando essas grandezas forem declaradas.

Phantom power é orientado pelo papel elétrico. O perfil `input` pode declarar
`phantom_power.provision`, com capacidade, tensão e corrente máxima. O perfil
`output` pode declarar `phantom_power.requirement` e
`phantom_power.tolerance`. Não existe `prohibits`: `tolerance.supported: false`
é a evidência negativa explícita. `enabled` e `currently_enabled` não pertencem
ao catálogo; representam estado de configuração de uma futura camada de
projeto/runtime.

A ausência de qualquer característica elétrica significa `UNKNOWN`, não
`unsupported`. A extensão é aditiva: records 3.4 continuam estruturalmente
válidos sem `electrical_characteristics`. Campos elétricos legados em
`signal_characteristics`, como `balanced`, `input_impedance`,
`output_impedance`, `maximum_level` e `phantom_power`, continuam aceitos
temporariamente. Records revisados devem migrar somente fatos confirmados,
com revisão de papel, unidade e fonte; não há migração automática.

### Extensão elétrica do Schema 3.6

O Schema 3.6 mantém a estrutura 3.5 e adiciona `variants` localmente em
`electrical_characteristics.input` e `electrical_characteristics.output`.
Uma variant pertence ao perfil elétrico do papel correspondente: `output` é
resolvido para `SOURCE` e `input` para `TARGET`.

Cada variant possui `conditions` e pelo menos uma propriedade de payload. A
única condição permitida nesta versão é `conditions.balance_mode`, com valor
`balanced` ou `unbalanced`. Não há condições para classe de nível, carga,
estado runtime, operadores booleanos, expressões aninhadas ou chaves livres.

O perfil base contém propriedades incondicionais. A variant não substitui o
perfil inteiro; ela contém somente propriedades condicionadas. Variants
parciais são válidas e a ausência de uma variant significa `UNKNOWN` para a
propriedade naquele modo. Não existe fallback implícito.

Uma única variant por `balance_mode` é permitida semanticamente, mesmo que
variants duplicadas contenham propriedades diferentes. A condição deve
corresponder a um valor declarado em `profile.balance_modes`. Essas duas
regras comparam objetos diferentes e são responsabilidade futura do Semantic
Validator, não do JSON Schema.

O payload de uma variant é limitado a `maximum_level` e `impedance`. A
impedância pode declarar `nominal` e `upper_bound`; `nominal` e
`upper_bound` podem coexistir. `upper_bound` exige `value`, `unit` e
`inclusive`, e aceita opcionalmente `note`. `inclusive: false` representa
`<` e `inclusive: true` representa `<=`. `lower_bound`, `range` e operadores
genéricos não fazem parte desta versão.

`nominal_levels`, `balance_modes`, `operating_level_classes`,
`minimum_load_impedance` e qualquer forma de phantom power não pertencem ao
payload de variants. Phantom power permanece modelado somente nos perfis
base existentes.

A regra de não combinar uma propriedade base com a mesma propriedade em uma
variant também é semântica. Uma propriedade base e outra propriedade
condicionada podem coexistir. O Schema garante a forma, mas não tenta
resolver essas relações cross-object.

`measurement` global permanece inalterado. `impedance` continua sendo
informacional para compatibilidade; a extensão não cria regras de
incompatibilidade por impedância nem exige alteração do Compatibility
Analyzer.

## Restrições proprietárias

`connection_constraints` possui ID próprio e registra o `protocol_family` requerido, o papel da interface remota, `allowed_targets` e `denied_targets`. Cada alvo pode selecionar equipamento por ID, fabricante, modelo ou família e pode restringir `remote_interface_id` ou `remote_interface_role`. `allowed_targets.exhaustive` informa se a lista permitida é exaustiva.

Para um link proprietário, a capability com `proprietary: true` deve declarar `protocol_family`. Essa é a fonte canônica do protocolo. Se a restrição também declarar `protocol_family`, ele deve ser idêntico ao da capability; essa consistência exige validação semântica futura, pois JSON Schema não consegue comparar facilmente dois caminhos arbitrários do documento.

O schema apenas modela os dados. Não implementa o motor que compara connector, signal, características elétricas, protocolo, alvos permitidos ou alvos negados.

## Compatibilidades conhecidas

Cada `known_compatibilities` possui ID, `relation`, alvo de equipamento ou família/modelo e pode indicar `local_interface_id`, `remote_interface_id`, `remote_interface_role` e `protocol_family`. Isso registra uma relação validada sem confundir uma recomendação conhecida com uma regra geral de compatibilidade.

## Capacidades de comunicação

`communication_capabilities` descreve uma capacidade funcional de comunicação, não uma porta. Ela exige ID local, `type`, direção funcional e `interface_assignment`. `media_type` e `protocol_family` são opcionais quando aplicáveis.

`protocol_family` deve ser preenchido quando a capability representa um protocolo ou família tecnicamente identificável, como Dante, AES67 ou Q-LAN. Sua ausência não significa ausência de comunicação, apenas que nenhuma família de protocolo foi identificada ou documentada para aquela capability. Não se deve inventar valores como `unknown`, `proprietary`, `qsys` ou `management` apenas para satisfazer o schema.

`interface_assignment.allowed_interface_ids` referencia as interfaces físicas locais sem copiar sua definição. O `mode` declara o comportamento permitido pelo produto:

- `fixed`: exatamente uma interface pode operar a capability.
- `configurable`: o usuário pode escolher uma interface entre as permitidas.
- `simultaneous`: duas ou mais interfaces podem operar ao mesmo tempo.
- `redundant`: duas ou mais interfaces são caminhos redundantes.
- `segregated`: a capability pode ser distribuída conforme a segregação declarada no cadastro.

Uma porta Ethernet não recebe automaticamente capacidades de rede. LAN A, LAN B, áudio em rede, controle, gerenciamento e redundância precisam ser declarados por capabilities e assignments explícitos. O schema não presume que todas as interfaces Ethernet suportem todos os modos.

## Capacidade e recursos compartilhados

`communication_capabilities.capacity` representa somente um limite próprio, local e específico daquela capability. Usa valores numéricos para canais, flows, streams, sessões, endpoints e largura de banda. `other_limits` permite limites adicionais identificados sem recorrer a strings como `"8 channels"`.

Quando capabilities compartilham um recurso interno, elas referenciam o mesmo `resource_pool_id`. O pool declara a capacidade total compartilhada. Uma capability pode ter somente `capacity`, somente `resource_pool_id` ou ambos. Por exemplo, Dante pode ter capacidade própria de 8 x 8 e também consumir o pool geral de áudio de rede de 64 x 64; Q-LAN e AES67 podem somente referenciar esse pool quando não houver limite próprio independente documentado.

Capacities próprias e pools não são aditivos automaticamente. Uma licença que altera a capacidade própria de Dante não altera automaticamente o pool; uma licença que altera o pool não duplica esse limite nas capabilities que o referenciam. O schema registra essas declarações, mas não calcula capacidade efetiva nem valida consumo; isso pertence a um semantic validator futuro.

### Exemplos v3.1

Conector simples, sem detalhamento de pinos:

```json
{
  "id": "lan-a",
  "connector": "RJ45",
  "signals": [{ "id": "ethernet", "name": "Ethernet", "signal_type": "network" }]
}
```

Conector compartilhado com GPIO:

```json
{
  "id": "gpio-terminal-block",
  "label": "GPIO terminal block",
  "connector_type": "10-pin Euroblock",
  "connection_points": [
    { "id": "gpio-in-1", "label": "GPIO input 1", "role": "signal" },
    { "id": "gpio-common", "label": "Common", "role": "common" }
  ]
}
```

Interface funcional usando vários pontos físicos:

```json
{
  "id": "rs232-1",
  "connector": "3-position 3.5 mm connector",
  "physical_connection": {
    "connector_id": "rs232-com-1",
    "connection_point_ids": ["tx", "rx", "ground"]
  }
}
```

Capability com capacidade própria e pool compartilhado:

```json
{
  "id": "dante-network-audio",
  "capacity": { "rx_channels": 8, "tx_channels": 8 },
  "resource_pool_id": "network-audio-pool"
}
```

Capability somente com pool compartilhado:

```json
{
  "id": "q-lan-network-audio",
  "resource_pool_id": "network-audio-pool"
}
```

## Modificadores e capacidade efetiva

`capability_modifiers` registra modificadores possíveis, como `license`, `installed_module`, `firmware_feature`, `configuration` e `hardware_option`. Cada modificador pode afetar uma capability, um pool ou uma capability genérica, alterando `capacity` ou `availability`. `source_equipment_id` permite referenciar o equipamento/módulo que origina o modificador, sem duplicar seus dados.

O cadastro de catálogo contém apenas a capacidade base e os modificadores possíveis. Ele não contém `effective_capacity` fixa. A capacidade efetiva deverá ser calculada futuramente a partir da capacidade base mais a configuração, licenças e módulos instalados em uma instância.

## Modularidade e composição

`modularity.role` pode ser `standalone`, `chassis`, `module` ou `hybrid`. Chassis e hybrid declaram `slots` individuais com ID, label, `slot_type`, índice/posição e restrições explícitas em `accepts`. Modules declaram `module_type` e `compatible_slot_types`; compatibilidade não depende somente de fabricante/modelo e pode incluir interface mecânica e outras condições.

`slot_type` é o tipo/identidade estrutural do slot. `module_type` é o tipo estrutural/funcional do módulo. `slot.accepts.module_types` declara quais tipos de módulo o slot aceita; `module.compatible_slot_types` declara em quais tipos de slot o módulo pode ser instalado. Essas declarações são complementares, não duplicação acidental: o slot declara o que aceita e o módulo declara onde pode entrar. Uma futura validação semântica poderá comparar os dois lados; o JSON Schema não faz essa comparação.

`module_types` é opcional, contém strings reutilizáveis por qualquer fabricante e não é um catálogo global. Restrições existentes por `manufacturers`, `product_families` e `models` continuam disponíveis e podem coexistir com `module_types`. Nesta versão não há semântica genérica de AND/OR para combinar restrições; a interpretação conjunta fica adiada para um semantic validator futuro.

Exemplo complementar:

```json
{
  "slot_type": "dmf-ci-8-card-slot",
  "accepts": { "module_types": ["dm-nvx-c-card"] }
}
```

```json
{
  "module_type": "dm-nvx-c-card",
  "compatible_slot_types": ["dmf-ci-8-card-slot"]
}
```

O catálogo de um chassis descreve quais slots existem e quais módulos são aceitos. Não declara quais módulos estão instalados em uma unidade específica. A instalação real pertence a uma futura camada de instância/configuração. `composition` contém somente metadados para orientar essa futura composição, incluindo a possibilidade de derivar capacidades de módulos instalados.

As interfaces físicas de um módulo pertencem ao cadastro do módulo. Elas não devem ser copiadas para o chassis. Um compositor futuro poderá endereçar uma interface por caminho hierárquico, como `chassis-instance/slot-3/module-instance/hdmi-input-1`, combinando IDs de instância, slot, módulo e interface.

## Alimentação e unidades

`power.sources` é uma lista de fontes alternativas ou métodos de alimentação. Cada source possui ID, método (`AC`, `DC`, `PoE` ou `other`) e pode registrar connector, voltage, frequency, current, power available e consumo típico/máximo. Não há duplicação de tensão ou frequência em outro nível da fonte.

`poe_consumed` representa energia PoE recebida/consumida pelo equipamento; `power.poe_supplied` representa energia PoE fornecida a outros equipamentos e referencia a interface local que a fornece. Dissipação térmica fica separada do consumo elétrico. Campos estruturados `unit` armazenam a identidade canônica do Vocabulary, como `watt`, `volt`, `ampere`, `hertz`, `btu-per-hour`, `kilogram` e `millimeter`; o símbolo de apresentação, como `W`, `V` ou `Hz`, é derivado de `vocab/units.json` e não é persistido junto ao valor.

`unit` e símbolo de apresentação são conceitos diferentes. O JSON Schema v3.7 valida que `unit` é uma string estrutural não vazia, mas não verifica a existência do ID no Vocabulary externo. A resolução da identidade canônica pertence à validação de Vocabulary/semântica futura. Não há conversão de unidades, prefixos ou aritmética de unidades neste modelo.

## Extensibilidade e evolução

O modelo reserva estruturas para requisitos de infraestrutura, fluxo funcional, compatibilidades validadas e representação gráfica. `physical_connectors[].connection_points[]` possui ID próprio e representa pontos físicos; `graphic_representation.connection_points[]` continua sendo uma estrutura independente para pontos gráficos associados a interfaces. `position` fica disponível no ponto físico para uso quando a fonte comprovar posição ou quando a representação gráfica justificar. A associação por ID não depende do label, embora a existência e unicidade dos connectors, points e interfaces referenciados precisem ser verificadas fora do JSON Schema.

As estruturas de comunicação e modularidade são universais: não distinguem DSP, switch, amplificador, câmera, display, extensor, codec ou microfone por campos específicos. O conteúdo especializado pode ser adicionado por capabilities e extensões, mas protocolos de rede não devem ser confundidos com áudio, e slots não devem ser acoplados a um fabricante.

## Versionamento e validação

`schema_version` é a versão SemVer da estrutura do documento, por exemplo `3.7.0`. `revision` é a revisão do cadastro de um equipamento específico e pode mudar sem alterar a estrutura do schema. JSON Schema valida tipos, presença e formatos locais, mas não garante integridade referencial, unicidade global ou local de IDs, coerência entre protocol families, existência de interfaces atribuídas, existência de physical connectors ou connection points referenciados, compatibilidade entre interfaces, compatibilidade entre `slot.accepts.module_types` e `module.compatible_slot_types`, capacidade total de pools, consistência de unidades ou existência dos IDs no Vocabulary externo. Um semantic validator futuro será necessário para essas regras.

Informações do fabricante ficam nos campos oficiais do equipamento. Conhecimento produzido pela empresa fica exclusivamente em `internal_knowledge`, evitando misturar fontes e níveis de autoridade.

O Core 8 Flex serve como stress test conceitual do schema, mas não define seus campos nem cria dependência com Q-SYS.
