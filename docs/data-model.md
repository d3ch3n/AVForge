# Decisões do Modelo de Dados

## Escopo

`equipment.schema.json` define um modelo universal de equipamento AV, em vez de um schema dedicado a um fabricante ou categoria. Campos específicos podem ser acomodados em `capabilities`, `extensions` e `custom_fields`, preservando um núcleo comum e IDs estáveis para relações futuras. O schema não contém campos específicos do Q-SYS.

## Identidade e escopo dos IDs

O `id` do equipamento é obrigatório. Cada porta física conectável deve ter seu próprio `interfaces[].id`; `quantity` só expressa uma quantidade agregada de elementos equivalentes e nunca identifica portas individuais. Signals/capabilities, restrições, relações de compatibilidade e connection points também possuem IDs próprios. Esses IDs são estáveis no cadastro e não devem depender de labels visuais.

IDs usados em `functional_behavior` são referências a signals/capabilities ou entidades locais do mesmo equipamento. `interface_id` em `connection_points` e `poe_supplied` referencia uma interface local. `target_equipment_id` e `remote_interface_id` em relações apontam para entidades de outro cadastro quando esse cadastro existir. O formato do ID é validado, mas sua unicidade global e a existência do alvo não são garantidas pelo JSON Schema.

## Interfaces não são apenas conectores

Cada interface possui um `connector` físico e uma lista independente de `signals`. Essa separação é necessária porque o mesmo conector pode transportar tecnologias incompatíveis. Uma interface RJ45, por exemplo, pode representar LAN, HDBaseT ou um protocolo proprietário.

`signal_type` é uma categoria ampla, como `audio`, `video`, `network`, `control` ou `data`. `signal_family` identifica uma família técnica, como `analog-audio`, `AES3`, `Ethernet` ou `HDBaseT`; `signal_format` descreve um formato quando aplicável; `protocol_family` identifica o protocolo ou ecossistema específico. `connector` não deve receber valores de sinal ou protocolo.

Características físicas e elétricas da porta pertencem a `electrical_characteristics` da interface. Características do sinal, formato ou variante pertencem a `signal_characteristics` e aos campos da capability. O schema mantém esses objetos extensíveis, mas não define ainda um vocabulário completo para impedância, nível, largura de banda ou resolução.

`interface.direction` descreve a direção geral da porta. Uma capability pode declarar outra `direction`, permitindo que uma interface bidirecional tenha capacidades de entrada e saída diferentes.

## Restrições proprietárias

`connection_constraints` possui ID próprio e registra o `protocol_family` requerido, o papel da interface remota, `allowed_targets` e `denied_targets`. Cada alvo pode selecionar equipamento por ID, fabricante, modelo ou família e pode restringir `remote_interface_id` ou `remote_interface_role`. `allowed_targets.exhaustive` informa se a lista permitida é exaustiva.

Para um link proprietário, a capability com `proprietary: true` deve declarar `protocol_family`. Essa é a fonte canônica do protocolo. Se a restrição também declarar `protocol_family`, ele deve ser idêntico ao da capability; essa consistência exige validação semântica futura, pois JSON Schema não consegue comparar facilmente dois caminhos arbitrários do documento.

O schema apenas modela os dados. Não implementa o motor que compara connector, signal, características elétricas, protocolo, alvos permitidos ou alvos negados.

## Compatibilidades conhecidas

Cada `known_compatibilities` possui ID, `relation`, alvo de equipamento ou família/modelo e pode indicar `local_interface_id`, `remote_interface_id`, `remote_interface_role` e `protocol_family`. Isso registra uma relação validada sem confundir uma recomendação conhecida com uma regra geral de compatibilidade.

## Capacidades de comunicação

`communication_capabilities` descreve uma capacidade funcional de comunicação, não uma porta. Ela exige ID local, `type`, `protocol_family`, direção funcional e `interface_assignment`. `media_type` é opcional quando aplicável.

`interface_assignment.allowed_interface_ids` referencia as interfaces físicas locais sem copiar sua definição. O `mode` declara o comportamento permitido pelo produto:

- `fixed`: exatamente uma interface pode operar a capability.
- `configurable`: o usuário pode escolher uma interface entre as permitidas.
- `simultaneous`: duas ou mais interfaces podem operar ao mesmo tempo.
- `redundant`: duas ou mais interfaces são caminhos redundantes.
- `segregated`: a capability pode ser distribuída conforme a segregação declarada no cadastro.

Uma porta Ethernet não recebe automaticamente capacidades de rede. LAN A, LAN B, áudio em rede, controle, gerenciamento e redundância precisam ser declarados por capabilities e assignments explícitos. O schema não presume que todas as interfaces Ethernet suportem todos os modos.

## Capacidade e recursos compartilhados

`communication_capabilities.capacity` usa valores numéricos para canais, flows, streams, sessões, endpoints e largura de banda. `other_limits` permite limites adicionais identificados sem recorrer a strings como `"8 channels"`.

Quando capabilities compartilham um recurso interno, elas referenciam o mesmo `resource_pool_id`. O pool declara a capacidade total compartilhada; capabilities que o referenciam não devem ser somadas como recursos independentes. A soma e a verificação de limites serão responsabilidade de um semantic validator futuro.

## Modificadores e capacidade efetiva

`capability_modifiers` registra modificadores possíveis, como `license`, `installed_module`, `firmware_feature`, `configuration` e `hardware_option`. Cada modificador pode afetar uma capability, um pool ou uma capability genérica, alterando `capacity` ou `availability`. `source_equipment_id` permite referenciar o equipamento/módulo que origina o modificador, sem duplicar seus dados.

O cadastro de catálogo contém apenas a capacidade base e os modificadores possíveis. Ele não contém `effective_capacity` fixa. A capacidade efetiva deverá ser calculada futuramente a partir da capacidade base mais a configuração, licenças e módulos instalados em uma instância.

## Modularidade e composição

`modularity.role` pode ser `standalone`, `chassis`, `module` ou `hybrid`. Chassis e hybrid declaram `slots` individuais com ID, label, `slot_type`, índice/posição e restrições explícitas em `accepts`. Modules declaram `module_type` e `compatible_slot_types`; compatibilidade não depende somente de fabricante/modelo e pode incluir interface mecânica e outras condições.

O catálogo de um chassis descreve quais slots existem e quais módulos são aceitos. Não declara quais módulos estão instalados em uma unidade específica. A instalação real pertence a uma futura camada de instância/configuração. `composition` contém somente metadados para orientar essa futura composição, incluindo a possibilidade de derivar capacidades de módulos instalados.

As interfaces físicas de um módulo pertencem ao cadastro do módulo. Elas não devem ser copiadas para o chassis. Um compositor futuro poderá endereçar uma interface por caminho hierárquico, como `chassis-instance/slot-3/module-instance/hdmi-input-1`, combinando IDs de instância, slot, módulo e interface.

## Alimentação e unidades

`power.sources` é uma lista de fontes alternativas ou métodos de alimentação. Cada source possui ID, método (`AC`, `DC`, `PoE` ou `other`) e pode registrar connector, voltage, frequency, current, power available e consumo típico/máximo. Não há duplicação de tensão ou frequência em outro nível da fonte.

`poe_consumed` representa energia PoE recebida/consumida pelo equipamento; `power.poe_supplied` representa energia PoE fornecida a outros equipamentos e referencia a interface local que a fornece. Dissipação térmica fica separada do consumo elétrico. Unidades calculáveis são controladas por valores canônicos: `W`, `V`, `A`, `Hz`, `BTU/h`, `kg` e `mm`.

## Extensibilidade e evolução

O modelo reserva estruturas para requisitos de infraestrutura, fluxo funcional, compatibilidades validadas e representação gráfica. Cada `connection_point` possui ID próprio e exatamente um `interface_id`; `position` e `metadata` ficam disponíveis para evolução gráfica. A associação por ID não depende do label, embora a existência e unicidade da interface referenciada precisem ser verificadas fora do JSON Schema.

As estruturas de comunicação e modularidade são universais: não distinguem DSP, switch, amplificador, câmera, display, extensor, codec ou microfone por campos específicos. O conteúdo especializado pode ser adicionado por capabilities e extensões, mas protocolos de rede não devem ser confundidos com áudio, e slots não devem ser acoplados a um fabricante.

## Versionamento e validação

`schema_version` é a versão SemVer da estrutura do documento, por exemplo `3.0.0`. `revision` é a revisão do cadastro de um equipamento específico e pode mudar sem alterar a estrutura do schema. JSON Schema valida tipos, presença e formatos locais, mas não garante integridade referencial, unicidade global ou local de IDs, coerência entre protocol families, existência de interfaces atribuídas, compatibilidade entre interfaces, capacidade total de pools ou consistência de unidades. Um semantic validator futuro será necessário para essas regras.

Informações do fabricante ficam nos campos oficiais do equipamento. Conhecimento produzido pela empresa fica exclusivamente em `internal_knowledge`, evitando misturar fontes e níveis de autoridade.

O Core 8 Flex serve como stress test conceitual do schema, mas não define seus campos nem cria dependência com Q-SYS.
