# AVForge

O AVForge é um sistema de engenharia audiovisual. O objetivo de longo prazo é manter uma biblioteca estruturada de equipamentos AV, representar suas interfaces e compatibilidades e, futuramente, gerar diagramas técnicos/DWG automaticamente.

## Status atual

Esta primeira fase é exclusivamente a modelagem estruturada de equipamentos. Ainda não há agentes, IA, banco de dados, código de aplicação ou geração de desenhos. A versão 3.1 estrutural do schema está em `schemas/equipment.schema.json` e os equipamentos ficam em `equipment/<vendor>/`.

O Q-SYS Core 8 Flex é usado apenas como stress test conceitual. O modelo deve permanecer universal para DSPs, câmeras, displays, codecs, switches, amplificadores, microfones, interfaces USB, extensores e outras categorias AV.

## Interfaces e compatibilidade

`connector` descreve exclusivamente o conector físico. `direction` descreve a direção da interface, enquanto cada signal pode declarar sua própria direção. `signal_type` é uma categoria ampla; `signal_family`/`signal_format` descrevem a família ou formato; `protocol_family` identifica o protocolo/ecossistema. Portanto, um RJ45 pode transportar LAN, HDBaseT, áudio proprietário, vídeo proprietário ou outro link; o tipo de conector nunca determina compatibilidade sozinho.

Interfaces proprietárias devem declarar explicitamente seu `protocol_family` na capability proprietária e podem declarar `connection_constraints` com alvos permitidos ou negados, fabricante, modelo, família e interface remota. Compatibilidades conhecidas representam relações já validadas.

## Organização dos dados

O schema também reserva estruturas para infraestrutura, comportamento funcional, papéis no projeto e futura representação gráfica com blocos e pontos de conexão. `power.sources` permite múltiplos métodos de alimentação, com unidades controladas para tensão, corrente, frequência, potência, peso, dimensões e dissipação. `poe_consumed` e `poe_supplied` são separados. Dados oficiais do fabricante devem permanecer separados de `internal_knowledge`, que contém conhecimento interno da empresa.

`communication_capabilities` modela capacidades funcionais sem duplicar a porta física. Cada capability referencia interfaces por IDs e declara explicitamente seu modo de associação (`fixed`, `configurable`, `simultaneous`, `redundant` ou `segregated`). `protocol_family` é opcional e só deve ser preenchido quando tecnicamente identificável/documentado; sua ausência não significa ausência de comunicação. Capacidades numéricas próprias ficam em `capacity`; `resource_pools` representam limites compartilhados e não são somados automaticamente às capacidades; `capability_modifiers` representam licenças, módulos e outras condições que alteram disponibilidade ou capacidade.

`physical_connectors` representa conectores físicos reais, e seus `connection_points` representam pinos, terminais, contatos ou posições. Uma `interface` continua sendo uma função conectável independente e pode referenciar opcionalmente um conector físico e um ou mais pontos por `physical_connection`. Isso permite representar um único borne multipinos compartilhado por várias interfaces funcionais sem confundir conector, interface e protocolo. A estrutura é opcional para preservar a validade de registros antigos.

`modularity` classifica equipamentos como `standalone`, `chassis`, `module` ou `hybrid`. Chassis declaram slots individuais e módulos declaram tipos de slot compatíveis. O catálogo descreve slots e possibilidades, mas não módulos instalados em uma unidade específica; essa composição será uma camada futura.

IDs identificam o equipamento, cada porta física conectável, cada signal/capability, cada capability de comunicação, pool, modificador, slot, restrição, relação de compatibilidade e connection point. `quantity` é somente uma contagem de elementos agregados e nunca substitui IDs individuais. `schema_version` usa SemVer para a estrutura; `revision` identifica a revisão do cadastro. Não invente especificações ausentes. Consulte `docs/data-model.md` para as decisões, limites de integridade referencial e necessidade futura de um semantic validator.
