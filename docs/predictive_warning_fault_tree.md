# Árvore lógica conceitual do aviso preditivo

Esta estrutura é inspirada em FTA apenas como mapa lógico de problemas do
demonstrador. Não é análise de certificação, não atribui severidade, não usa
probability budgets regulatórios e não pressupõe independência entre ramos.

**Top event interno:** aviso de manutenção do demonstrador não fornecido com a
antecedência requerida.

```mermaid
flowchart TD
    TOP["Aviso não fornecido com antecedência requerida"]
    OR{{OR lógico}}
    TOP --> OR
    OR --> A["Telemetria indisponível ou inválida"]
    OR --> B["Preprocessing incorreto"]
    OR --> C["Modelo ou componente indisponível"]
    OR --> D["Risco subestimado"]
    OR --> E["Calibração inadequada"]
    OR --> F["Threshold inadequado"]
    OR --> G["Filtragem atrasa evidência"]
    OR --> H["Saída não apresentada ao usuário"]
    C --> C1["Artefato base ausente"]
    C --> C2["Meta-modelo ou calibrador ausente"]
    D --> D1["Modelo base subestima"]
    D --> D2["Dependência comum afeta vários modelos"]
    F --> F1["Threshold excessivamente alto"]
    F --> F2["Persistência acrescenta atraso"]
    G --> G1["Pacote perdido ou atrasado"]
    G --> G2["Sensor necessário omitido"]
    G --> G3["Valor mantido tratado como atual"]
    G --> G4["Modo adaptativo não aumenta frequência"]
    G --> G5["Cadência de inferência posterga atualização"]
```

O conector OR indica que qualquer ramo pode ser suficiente para o top event.
Vários ramos podem ocorrer juntos: telemetria inválida pode causar preprocessing
incorreto, subestimação e indisponibilidade; uma configuração de horizonte
incorreta pode afetar modelo, calibrador e threshold. Portanto, somar
probabilidades ou multiplicar ramos como independentes seria injustificado.

Controles atuais incluem validação explícita da entrada, idade por sensor,
`telemetry_stale`, marca de transmissão, cadência de inferência configurável,
status `valid`, `degraded` e `unavailable`, alinhamento por chave/horizonte,
calibração cross-fitted, thresholds versionados, persistência configurável,
hashes e manifesto congelado. CLI e Streamlit apresentam estados e causas;
testes controlados cobrem modelo/artefato ausente, staleness, preprocessing e
risco inválido. Timestamps físicos, transporte real e objetivos de antecedência
industriais seguem fora da implementação. A árvore não foi quantificada.

## Extensão para a mudança de fluxo (0.11.0)

O ramo **B — preprocessing incorreto** inclui agora HLV tratado como amostra
nova, recuperação de sensor que não foi transmitido e incompatibilidade entre
artefato treinado e schema filtrado. O ramo **G — filtragem atrasa evidência**
inclui cadência reduzida que omite uma mudança, staleness que produz
`degraded/unavailable`, sensor requerido nunca inicializado e inferência apenas
na transmissão que posterga uma oportunidade de alerta. Esses ramos podem
compartilhar telemetria, preprocessing, runtime e configuração; nenhuma
independência é assumida e nenhum probability budget é calculado.

Durante a execução local, pacotes perdidos ou atrasados continuam modos
conceituais: o estudo mede políticas sequenciais e hold-last-value, não um
enlace físico. A evidência quantitativa de cada ramo é limitada às tabelas de
validation e ao recibo específico do `test_internal` após o freeze.
